import os
import sys
import datetime
import json
import re
from typing import Any

from google.adk import Agent, Context, Workflow
from google.adk.models import Gemini
from google.adk.apps import App
from google.adk.workflow._base_node import START
from google.adk.events.request_input import RequestInput
from google.adk.tools import AgentTool, McpToolset
from mcp import StdioServerParameters

from app.config import config

# ---------------------------------------------------------------------------
# Setup MCP Toolset
# ---------------------------------------------------------------------------
# Launch local FastMCP server in a subprocess using same virtual environment
mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
    )
)

# Initialize Gemini Model
model_obj = Gemini(model=config.model)

# ---------------------------------------------------------------------------
# Specialized Sub-Agents
# ---------------------------------------------------------------------------
medication_agent = Agent(
    name="medication_agent",
    model=model_obj,
    instruction="""You are a specialized medication assistant.
You help retrieve and update patient medication schedules.
Use the MCP tools provided to read or modify medication data.

If the query starts with 'Execute approved update: ', extract the patient_id, medication, dosage, and frequency, and call the `update_medication_schedule` tool directly to save the changes. Confirm that it has been updated in the patient record.
""",
    tools=[mcp_toolset]
)

symptom_agent = Agent(
    name="symptom_agent",
    model=model_obj,
    instruction="""You are a specialized symptom assistant.
You help log reported symptoms and evaluate their severity.
Use the MCP tools to log symptoms in the patient records.
If a symptom is reported as severe, advise the user to seek immediate professional medical attention.""",
    tools=[mcp_toolset]
)

# ---------------------------------------------------------------------------
# Function Tool for Coordinator Agent
# ---------------------------------------------------------------------------
def request_medication_update_approval(
    ctx: Context,
    patient_id: str,
    medication: str,
    dosage: str,
    frequency: str
) -> str:
    """Request human confirmation/approval to update or add a patient's medication schedule.
    Use this tool whenever the user requests a change, update, addition, or removal of any medication.

    Args:
        patient_id: Unique identifier for the patient (e.g. 'patient_1').
        medication: Name of the medication.
        dosage: Dosage of the medication (e.g. '10mg').
        frequency: How often it should be taken (e.g. 'once daily').
    """
    ctx.state['needs_approval'] = True
    ctx.state['approval_message'] = f"Do you approve updating medication schedule for {patient_id}: {medication} to {dosage} ({frequency})?"
    ctx.state['pending_action'] = {
        "patient_id": patient_id,
        "medication": medication,
        "dosage": dosage,
        "frequency": frequency
    }
    return f"Medication change request registered for {medication}. Pausing for coordinator approval."

# ---------------------------------------------------------------------------
# Coordinator Agent (Orchestrator)
# ---------------------------------------------------------------------------
coordinator_agent = Agent(
    name="coordinator_agent",
    model=model_obj,
    instruction="""You are the central Care Coordinator.
Your job is to analyze user queries and delegate tasks to specialized sub-agents or tools:
- Use medication_agent to handle medication schedule queries.
- Use symptom_agent to log or query symptom reports.
- Use the MCP get_appointments tool for appointment queries.

SAFETY & FLOW DIRECTIVES:
1. If the user query is asking to add, modify, or update a medication dosage/schedule:
   - Do NOT update it directly.
   - You MUST call the `request_medication_update_approval` tool with the details (patient_id, medication, dosage, frequency).
   - Inform the user that the request has been submitted for approval.
2. For symptom queries or appointment checks, delegate immediately to the appropriate sub-agent or tool.
""",
    tools=[
        AgentTool(medication_agent),
        AgentTool(symptom_agent),
        request_medication_update_approval,
        mcp_toolset
    ]
)

# ---------------------------------------------------------------------------
# Workflow Helper Functions & Nodes
# ---------------------------------------------------------------------------
# PII Regexes
PHONE_REGEX = re.compile(r'\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b')
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
SSN_REGEX = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

# Prompt Injection Keywords
INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "system prompt",
    "override security",
    "bypass safety",
    "you are now",
    "developer mode",
    "prompt injection"
]

def audit_log(severity: str, action: str, details: dict):
    log_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "severity": severity,
        "action": action,
        "details": details
    }
    print(f"[AUDIT] {json.dumps(log_data)}")

def security_checkpoint(ctx: Context, node_input: Any) -> str:
    """Security node to check for prompt injections and scrub PII."""
    text = ""
    if isinstance(node_input, str):
        text = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        text = "".join([p.text for p in node_input.parts if p.text])
    else:
        text = str(node_input)

    lower_text = text.lower()
    
    # 1. Prompt Injection Detection
    for kw in INJECTION_KEYWORDS:
        if kw in lower_text:
            audit_log("CRITICAL", "PROMPT_INJECTION_DETECTED", {"keyword": kw, "input": text})
            ctx.route = "SECURITY_EVENT"
            return f"Security violation detected: keyword '{kw}'"

    # 2. PII Scrubbing
    scrubbed = text
    scrubbed = PHONE_REGEX.sub("[REDACTED_PHONE]", scrubbed)
    scrubbed = EMAIL_REGEX.sub("[REDACTED_EMAIL]", scrubbed)
    scrubbed = SSN_REGEX.sub("[REDACTED_SSN]", scrubbed)

    # 3. Domain specific dangerous dosage check
    dangerous_keywords = ["double my dose", "take double", "overdose", "double dose"]
    for kw in dangerous_keywords:
        if kw in lower_text:
            audit_log("WARNING", "DANGEROUS_DOSAGE_QUERY", {"keyword": kw, "input": text})
            ctx.state["security_warning"] = "Warning: Never double your dosage without consulting a doctor."

    # Save to state
    ctx.state["scrubbed_query"] = scrubbed
    audit_log("INFO", "QUERY_CLEANSED", {"original": text, "scrubbed": scrubbed})
    
    ctx.route = "SAFE"
    return scrubbed

def security_event_handler(ctx: Context, node_input: Any) -> str:
    """Terminal node returning security error."""
    return f"Access Denied: Your request was blocked by security checkpoint. Reason: {node_input}"

def human_approval_checkpoint(ctx: Context, node_input: Any):
    """Workflow checkpoint node for human-in-the-loop approval."""
    if ctx.state.get("needs_approval"):
        ctx.state["needs_approval"] = False  # Clear flag to avoid loop on resume
        msg = ctx.state.get("approval_message", "Do you approve this medication schedule update?")
        return RequestInput(
            interrupt_id="medication_update_approval",
            message=msg,
            response_schema=bool
        )
    # If no approval needed, pass through orchestrator's output
    return node_input

async def post_approval_handler(ctx: Context, node_input: Any) -> str:
    """Processes approval output and executes approved updates."""
    if isinstance(node_input, bool):
        if node_input is True:
            # Execute action using medication_agent
            action = ctx.state.get("pending_action")
            if action:
                patient_id = action.get("patient_id")
                med = action.get("medication")
                dosage = action.get("dosage")
                freq = action.get("frequency")
                
                # Execute agent dynamically
                cmd = f"Execute approved update: Update patient {patient_id} medication {med} to {dosage} {freq}"
                res = await ctx.run_node(medication_agent, node_input=cmd)
                return f"Verification successful! Medication schedule updated: {res}"
            return "Approval received, but no pending action details found."
        else:
            return "Update cancelled: The medication schedule update was rejected."
    
    # Pass through non-boolean inputs (no approval triggered)
    return str(node_input)

# ---------------------------------------------------------------------------
# ADK 2.0 Workflow Compilation
# ---------------------------------------------------------------------------
care_coordinator_workflow = Workflow(
    name="care_coordinator_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {
            "SAFE": coordinator_agent,
            "SECURITY_EVENT": security_event_handler
        }),
        (coordinator_agent, human_approval_checkpoint),
        (human_approval_checkpoint, post_approval_handler)
    ]
)

# Hook Workflow into App
app = App(
    root_agent=care_coordinator_workflow,
    name="app",
)

# Export root_agent for backward compatibility with tests
root_agent = care_coordinator_workflow
