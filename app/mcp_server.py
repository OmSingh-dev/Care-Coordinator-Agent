from mcp.server.fastmcp import FastMCP
import datetime

# Create FastMCP server instance
mcp = FastMCP("care-coordinator-server")

# In-memory mock database for patient information
PATIENTS_DATABASE = {
    "patient_1": {
        "name": "Jane Doe",
        "medications": [
            {"medication": "Lisinopril", "dosage": "10mg", "frequency": "once daily in the morning"},
            {"medication": "Metformin", "dosage": "500mg", "frequency": "twice daily with meals"},
            {"medication": "Aspirin", "dosage": "81mg", "frequency": "once daily"}
        ],
        "symptoms": [],
        "appointments": [
            {"date": "2026-07-10", "time": "10:00 AM", "doctor": "Dr. Sarah Jenkins (Cardiology)", "reason": "Follow-up checkup"},
            {"date": "2026-08-15", "time": "2:30 PM", "doctor": "Dr. Alan Mercer (Primary Care)", "reason": "Annual physical"}
        ]
    }
}

@mcp.tool()
def get_medications(patient_id: str) -> str:
    """Retrieve the current medication list and schedules for a patient.

    Args:
        patient_id: Unique identifier for the patient (e.g. 'patient_1').
    """
    patient = PATIENTS_DATABASE.get(patient_id)
    if not patient:
        return f"Patient with ID '{patient_id}' not found."

    meds = patient["medications"]
    if not meds:
        return f"No medications found for patient '{patient_id}'."

    output = f"Medications for {patient['name']} ({patient_id}):\n"
    for m in meds:
        output += f"- {m['medication']} ({m['dosage']}): {m['frequency']}\n"
    return output

@mcp.tool()
def update_medication_schedule(patient_id: str, medication: str, dosage: str, frequency: str) -> str:
    """Update or add a medication to the schedule for a patient.

    Args:
        patient_id: Unique identifier for the patient (e.g. 'patient_1').
        medication: Name of the medication to add or update.
        dosage: Dosage of the medication (e.g. '10mg').
        frequency: How often the medication should be taken (e.g. 'once daily').
    """
    patient = PATIENTS_DATABASE.get(patient_id)
    if not patient:
        return f"Patient with ID '{patient_id}' not found."

    # Search if medication exists, update it, otherwise add new
    found = False
    for m in patient["medications"]:
        if m["medication"].lower() == medication.lower():
            m["dosage"] = dosage
            m["frequency"] = frequency
            found = True
            break

    if not found:
        patient["medications"].append({
            "medication": medication,
            "dosage": dosage,
            "frequency": frequency
        })

    action = "Updated" if found else "Added"
    return f"Successfully {action} {medication} ({dosage}, {frequency}) for patient {patient['name']} ({patient_id})."

@mcp.tool()
def log_symptom(patient_id: str, symptom: str, severity: str, notes: str) -> str:
    """Log a symptom reported by the patient.

    Args:
        patient_id: Unique identifier for the patient (e.g. 'patient_1').
        symptom: The symptom reported (e.g. 'Headache', 'Nausea').
        severity: Severity level (e.g. 'Mild', 'Moderate', 'Severe').
        notes: Context or notes regarding the symptom.
    """
    patient = PATIENTS_DATABASE.get(patient_id)
    if not patient:
        return f"Patient with ID '{patient_id}' not found."

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "symptom": symptom,
        "severity": severity,
        "notes": notes
    }
    patient["symptoms"].append(log_entry)

    return f"Successfully logged symptom '{symptom}' (Severity: {severity}) for patient {patient['name']} ({patient_id}) at {timestamp}."

@mcp.tool()
def get_appointments(patient_id: str) -> str:
    """Get upcoming appointments for a patient.

    Args:
        patient_id: Unique identifier for the patient (e.g. 'patient_1').
    """
    patient = PATIENTS_DATABASE.get(patient_id)
    if not patient:
        return f"Patient with ID '{patient_id}' not found."

    apps = patient["appointments"]
    if not apps:
        return f"No upcoming appointments found for patient '{patient_id}'."

    output = f"Upcoming appointments for {patient['name']} ({patient_id}):\n"
    for a in apps:
        output += f"- {a['date']} at {a['time']} with {a['doctor']} - Reason: {a['reason']}\n"
    return output

if __name__ == "__main__":
    mcp.run("stdio")
