import os
import json
from difflib import SequenceMatcher
from openai import OpenAI

def get_client():
    return OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

SYSTEM_PROMPT = """You are an AI assistant for Optimal Solutions, a construction business.
You help the owner log business data by understanding natural language and extracting structured information.

You have access to these tools:

1. create_worker — Add a new worker
   Required: name, daily_rate
   Optional: phone, active (default true)

2. create_work_log — Log days worked
   Required: worker_name, project_name, days_worked, start_date (YYYY-MM-DD)
   Optional: note

3. add_expense — Record a project expense
   Required: project_name, amount, category, date (YYYY-MM-DD)
   Optional: description, note

4. add_invoice_item — Add a line item to an invoice
   Required: invoice_number, description, amount

5. query_project_profit — Look up profit for a project
   Required: project_name

6. set_reminder — Save a reminder to check later on the site
   Required: text
   Optional: due_date (YYYY-MM-DD)

7. create_customer — Add a new customer (client)
   Required: name
   Optional: email, phone, address

8. draft_proposal — Create a draft proposal (quote) for a customer
   Required: customer_name, title
   Optional: description, amount

9. query_invoice_status — Look up an invoice's status and amount
   Required: invoice_number (e.g. INV-0007)

10. query_job_summary — Contract, billed, paid, and profit for a job/project
   Required: project_name

Rules:
- NEVER invent or guess worker names, project names, or amounts not stated by the user
- If a required field is missing or unclear, set clarification_needed to a specific question
- Extract dates in YYYY-MM-DD format; if the user says "today" use today's date
- Match worker/project names as closely as possible to what the user said"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_worker",
            "description": "Add a new worker to the system",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "daily_rate": {"type": "number"},
                    "phone": {"type": "string"},
                    "active": {"type": "boolean"}
                },
                "required": ["name", "daily_rate"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_work_log",
            "description": "Log days worked by a worker on a project",
            "parameters": {
                "type": "object",
                "properties": {
                    "worker_name": {"type": "string"},
                    "project_name": {"type": "string"},
                    "days_worked": {"type": "number"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "note": {"type": "string"}
                },
                "required": ["worker_name", "project_name", "days_worked", "start_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": "Record an expense for a project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"},
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "description": {"type": "string"},
                    "note": {"type": "string"}
                },
                "required": ["project_name", "amount", "category", "date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_invoice_item",
            "description": "Add a line item to an invoice",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {"type": "string"},
                    "description": {"type": "string"},
                    "amount": {"type": "number"}
                },
                "required": ["invoice_number", "description", "amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_project_profit",
            "description": "Look up profit/loss for a project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"}
                },
                "required": ["project_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Save a reminder for the user to see on the site",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to be reminded about"},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD, optional"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_customer",
            "description": "Add a new customer (client)",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "address": {"type": "string"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "draft_proposal",
            "description": "Create a draft proposal (quote) for an existing customer",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string", "description": "optional first line item"},
                    "amount": {"type": "number", "description": "optional price for the line item"}
                },
                "required": ["customer_name", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_invoice_status",
            "description": "Look up an invoice's status and amount by its number",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {"type": "string", "description": "e.g. INV-0007"}
                },
                "required": ["invoice_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_job_summary",
            "description": "Contract, billed, paid, and profit for a job/project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"}
                },
                "required": ["project_name"]
            }
        }
    }
]

REQUIRED_FIELDS = {
    "create_worker": ["name", "daily_rate"],
    "create_work_log": ["worker_name", "project_name", "days_worked", "start_date"],
    "add_expense": ["project_name", "amount", "category", "date"],
    "add_invoice_item": ["invoice_number", "description", "amount"],
    "query_project_profit": ["project_name"],
    "set_reminder": ["text"],
    "create_customer": ["name"],
    "draft_proposal": ["customer_name", "title"],
    "query_invoice_status": ["invoice_number"],
    "query_job_summary": ["project_name"],
}


def process_message(message, conversation_history=None):
    if conversation_history is None:
        conversation_history = []

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + \
               conversation_history + \
               [{"role": "user", "content": message}]

    response = get_client().chat.completions.create(
        model="gpt-4o",
        tools=TOOLS,
        tool_choice="auto",
        messages=messages
    )

    choice = response.choices[0].message

    # If the model called a tool, extract it
    if choice.tool_calls:
        call = choice.tool_calls[0]
        return {
            "tool": call.function.name,
            "confidence": "high",
            "data": json.loads(call.function.arguments),
            "clarification_needed": None
        }

    # Otherwise treat the text as a clarification
    return {
        "tool": None,
        "confidence": "low",
        "data": {},
        "clarification_needed": choice.content or "I couldn't understand that request. Could you rephrase it?"
    }


def validate_action(tool, data, db_session):
    from models import Worker, Project, Customer

    errors = []
    suggestions = []

    required = REQUIRED_FIELDS.get(tool, [])
    for field in required:
        if field not in data or data[field] is None or data[field] == "":
            errors.append(f"Missing required field: {field}")

    if errors:
        return {"valid": False, "errors": errors, "suggestions": suggestions}

    # Check worker exists for tools that reference one
    if "worker_name" in data:
        workers = db_session.query(Worker).all()
        worker_names = [w.name for w in workers]
        exact = next((w for w in workers if w.name.lower() == data["worker_name"].lower()), None)
        if not exact:
            errors.append(f"Worker '{data['worker_name']}' not found.")
            suggestions = fuzzy_match_worker(data["worker_name"], worker_names)

    # Check project exists for tools that reference one
    if "project_name" in data:
        projects = db_session.query(Project).all()
        project_names = [p.name for p in projects]
        exact = next((p for p in projects if p.name.lower() == data["project_name"].lower()), None)
        if not exact:
            errors.append(f"Project '{data['project_name']}' not found.")
            suggestions = fuzzy_match_project(data["project_name"], project_names)

    # Check customer exists for tools that reference one
    if "customer_name" in data:
        customers = db_session.query(Customer).all()
        customer_names = [c.name for c in customers]
        exact = next((c for c in customers if c.name.lower() == data["customer_name"].lower()), None)
        if not exact:
            errors.append(f"Customer '{data['customer_name']}' not found.")
            suggestions = fuzzy_match_project(data["customer_name"], customer_names)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "suggestions": suggestions
    }


def _similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def fuzzy_match_worker(name, workers_list):
    scored = [(w, _similarity(name, w)) for w in workers_list]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [w for w, score in scored[:3] if score > 0.3]


def fuzzy_match_project(name, projects_list):
    scored = [(p, _similarity(name, p)) for p in projects_list]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [p for p, score in scored[:3] if score > 0.3]
