from flask import Blueprint, jsonify
import state

bp = Blueprint("patients", __name__)


@bp.get("/api/patients")
def list_patients():
    """Return all patients (without EHR detail)."""
    return jsonify(list(state.PATIENTS.values()))


@bp.get("/api/patients/<patient_id>")
def get_patient(patient_id):
    """Return a patient record merged with their full EHR."""
    patient = state.PATIENTS.get(patient_id)
    if not patient:
        return jsonify({"error": "patient not found", "id": patient_id}), 404

    ehr = state.EHR.get(patient_id, {})
    return jsonify({**patient, "ehr": ehr})
