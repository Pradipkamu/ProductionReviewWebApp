import pytest
from fastapi import HTTPException

from app.api.fta import _decorate_tree, _validate_tree


def _node(node_id, status="NOT_INVESTIGATED"):
    return {"id": node_id, "label": node_id, "type": "BASIC_EVENT", "gate": None, "children": []}


def test_fta_or_gate_is_satisfied_when_one_child_is_confirmed():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "CONFIRMED", "b": "NOT_INVESTIGATED"})
    assert result["logic_state"] == "SATISFIED"


def test_fta_and_gate_requires_all_children_confirmed():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "AND",
        "children": [_node("a"), _node("b")],
    }
    partial = _decorate_tree(tree, {"a": "CONFIRMED", "b": "SUSPECTED"})
    complete = _decorate_tree(tree, {"a": "CONFIRMED", "b": "CONFIRMED"})
    assert partial["logic_state"] == "UNKNOWN"
    assert complete["logic_state"] == "SATISFIED"


def test_fta_gate_is_not_satisfied_when_all_or_children_are_ruled_out():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "RULED_OUT", "b": "RULED_OUT"})
    assert result["logic_state"] == "NOT_SATISFIED"


def test_fta_template_requires_unique_node_ids_and_valid_gate():
    valid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    assert len(_validate_tree(valid)) == 3
    duplicate = {**valid, "children": [_node("a"), _node("a")]}
    with pytest.raises(HTTPException):
        _validate_tree(duplicate)
    invalid_gate = {**valid, "gate": "XOR"}
    with pytest.raises(HTTPException):
        _validate_tree(invalid_gate)


def test_fta_tree_rejects_non_top_event_root():
    with pytest.raises(HTTPException):
        _validate_tree(_node("leaf"))


def test_fta_tree_rejects_empty_node_label():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{"id": "cause", "label": " ", "type": "BASIC_EVENT", "gate": None, "children": []}],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)


def test_fta_tree_rejects_nodes_without_logic_gate():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": None,
        "children": [_node("cause")],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)


def test_fta_and_gate_is_not_satisfied_when_one_child_is_ruled_out():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "AND",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "CONFIRMED", "b": "RULED_OUT"})
    assert result["logic_state"] == "NOT_SATISFIED"


def test_fta_or_gate_remains_unknown_until_a_cause_is_confirmed_or_all_ruled_out():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "SUSPECTED", "b": "NOT_INVESTIGATED"})
    assert result["logic_state"] == "UNKNOWN"


def test_fta_only_leaf_cause_nodes_can_be_classified_as_causes():
    from app.api.fta import _validate_cause_classification, FindingUpdate

    payload = FindingUpdate(
        investigation_status="CONFIRMED",
        verification_method="Micrometer measurement",
        is_root_cause=True,
    )
    _validate_cause_classification("BASIC_EVENT", payload)
    _validate_cause_classification("EXTERNAL_EVENT", payload)
    with pytest.raises(HTTPException):
        _validate_cause_classification("TOP_EVENT", payload)
    with pytest.raises(HTTPException):
        _validate_cause_classification("INTERMEDIATE_EVENT", payload)


def test_fta_cause_classification_requires_confirmed_status():
    from app.api.fta import _validate_cause_classification, FindingUpdate

    payload = FindingUpdate(
        investigation_status="SUSPECTED",
        is_root_cause=True,
    )
    with pytest.raises(HTTPException):
        _validate_cause_classification("BASIC_EVENT", payload)



def test_fta_action_link_requires_all_contexts_to_match_investigation_plant():
    from app.api.fta import _validate_action_plants

    _validate_action_plants("2020", {"2020"})
    _validate_action_plants("2020", set())
    with pytest.raises(HTTPException):
        _validate_action_plants("2020", {"2070"})
    with pytest.raises(HTTPException):
        _validate_action_plants("2020", {"2020", "2070"})
    with pytest.raises(HTTPException):
        _validate_action_plants(None, {"2020"})


def test_fta_active_investigation_unique_index_excludes_closed_records():
    from app.models import FtaInvestigation

    index = next(
        item for item in FtaInvestigation.__table__.indexes
        if item.name == "uq_fta_open_rejection_template"
    )
    assert index.unique is True
    assert "CLOSED" in str(index.dialect_options["sqlite"]["where"])


def test_fta_investigation_model_has_no_duplicate_index_names():
    from app.models import FtaInvestigation

    names = [index.name for index in FtaInvestigation.__table__.indexes]
    assert len(names) == len(set(names))
    assert "ix_fta_investigations_status" in names
    assert "ix_fta_investigations_plant" in names
    assert "uq_fta_open_rejection_template" in names


def test_fta_tree_rejects_children_on_leaf_event_nodes():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{
            "id": "basic", "label": "Basic cause", "type": "BASIC_EVENT", "gate": "OR",
            "children": [_node("nested")],
        }],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)


def test_fta_tree_requires_children_for_intermediate_events():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{
            "id": "intermediate", "label": "Intermediate event",
            "type": "INTERMEDIATE_EVENT", "gate": None, "children": [],
        }],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)


def test_fta_tree_rejects_nested_top_event_and_oversized_node_fields():
    nested_top = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{
            "id": "nested-top", "label": "Nested top", "type": "TOP_EVENT", "gate": "OR",
            "children": [_node("leaf")],
        }],
    }
    oversized_label = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{
            "id": "leaf", "label": "x" * 241, "type": "BASIC_EVENT", "gate": None, "children": [],
        }],
    }
    with pytest.raises(HTTPException):
        _validate_tree(nested_top)
    with pytest.raises(HTTPException):
        _validate_tree(oversized_label)


def test_fta_evidence_extensions_are_supported_by_secure_upload_validator():
    from app.api.fta import FTA_EVIDENCE_EXTENSIONS
    from app.services.file_security import SAFE_ATTACHMENT_MIME

    assert FTA_EVIDENCE_EXTENSIONS <= set(SAFE_ATTACHMENT_MIME)


def test_fta_role_matrix_keeps_management_read_only():
    from types import SimpleNamespace
    from app.api.fta import READ_ROLES, WRITE_ROLES, TEMPLATE_ROLES, _role

    management = SimpleNamespace(role="MANAGEMENT")
    _role(management, READ_ROLES)
    with pytest.raises(HTTPException) as exc:
        _role(management, WRITE_ROLES)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        _role(management, TEMPLATE_ROLES)


def test_fta_production_user_cannot_read_another_users_investigation():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.api.fta import _assert_investigation_access, READ_ROLES

    result = Mock()
    result.mappings.return_value.first.return_value = {
        "id": 7, "owner_id": 22, "created_by_id": 22, "status": "OPEN", "plant": "2020",
    }
    db = Mock()
    db.execute.return_value = result
    production_user = SimpleNamespace(id=11, role="PRODUCTION")

    with pytest.raises(HTTPException) as exc:
        _assert_investigation_access(db, 7, production_user, READ_ROLES)
    assert exc.value.status_code == 404


def test_fta_production_user_can_read_investigation_they_created_or_own():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.api.fta import _assert_investigation_access, READ_ROLES

    result = Mock()
    result.mappings.return_value.first.return_value = {
        "id": 7, "owner_id": 11, "created_by_id": 22, "status": "OPEN", "plant": "2020",
    }
    db = Mock()
    db.execute.return_value = result
    production_user = SimpleNamespace(id=11, role="PRODUCTION")

    row = _assert_investigation_access(db, 7, production_user, READ_ROLES)
    assert row["id"] == 7


def test_fta_created_action_is_marked_as_fta_and_does_not_require_whywhy():
    from app.models import Action

    action = Action(
        action_no="ACT-2026-99999",
        reference_date=__import__("datetime").date(2026, 11, 23),
        problem_description="FTA root-cause follow-up",
        action_description="Replace worn fixture locator",
        action_type="FTA",
        requires_whywhy=False,
    )
    assert action.action_type == "FTA"
    assert action.requires_whywhy is False


def test_fta_action_creation_endpoint_is_registered_separately_from_existing_action_link():
    from app.api.fta import router

    paths = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in router.routes
    }
    assert ("/fta/investigations/{investigation_id}/actions/create", ("POST",)) in paths
    assert ("/fta/investigations/{investigation_id}/actions", ("POST",)) in paths


def test_action_implementation_discovered_cause_requires_evidence_reference():
    from pydantic import ValidationError
    from app.api.fta import DiscoveredCauseCreate

    with pytest.raises(ValidationError):
        DiscoveredCauseCreate(cause_description="Different fixture alignment")
    payload = DiscoveredCauseCreate(
        cause_description="Different fixture alignment",
        evidence_reference="Trial report TR-2026-11",
    )
    assert payload.evidence_reference == "Trial report TR-2026-11"


def test_discovered_cause_review_requires_quality_decision_and_remarks():
    from pydantic import ValidationError
    from app.api.fta import DiscoveredCauseReview

    with pytest.raises(ValidationError):
        DiscoveredCauseReview(status="PENDING", review_remarks="Not a valid decision")
    payload = DiscoveredCauseReview(
        status="CONFIRMED",
        review_remarks="Confirmed after repeat trial.",
        verification_method="Three-piece dimensional validation",
    )
    assert payload.status == "CONFIRMED"


def test_discovered_cause_endpoints_are_registered():
    from app.api.fta import router

    paths = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in router.routes
    }
    assert ("/fta/actions/{action_id}/discovered-causes", ("POST",)) in paths
    assert ("/fta/discovered-causes/{cause_id}/review", ("POST",)) in paths



def test_shared_quality_phenomenon_model_exposes_fta_metadata():
    from app.models import QualityPhenomenon

    assert "fta_category" in QualityPhenomenon.__table__.columns
    assert "fta_description" in QualityPhenomenon.__table__.columns



def test_fta_recurrence_management_routes_are_registered():
    from app.api.fta import router

    paths = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert ("/fta/recurrence-candidates/{rejection_id}", ("GET",)) in paths
    assert ("/fta/investigations/{investigation_id}/recurrences", ("GET",)) in paths
    assert ("/fta/investigations/{investigation_id}/recurrences", ("POST",)) in paths
    assert ("/fta/recurrences/{recurrence_id}/review", ("PATCH",)) in paths
    assert ("/fta/recurrences/{recurrence_id}/related-investigation", ("POST",)) in paths


def test_fta_recurrence_model_preserves_separate_event_and_parent_links():
    from app.models import FtaRecurrence

    columns = FtaRecurrence.__table__.columns
    assert columns["original_investigation_id"].nullable is False
    assert columns["rejection_id"].nullable is False
    assert columns["recurrence_reason"].nullable is False
    assert columns["related_investigation_id"].nullable is True
    assert columns["previous_action_status"].nullable is True
    assert columns["previous_verification_result"].nullable is True
    assert any(index.name == "ix_fta_recurrences_original_investigation_id"
               for index in FtaRecurrence.__table__.indexes)
    assert any(constraint.name == "uq_fta_recurrences_rejection_id"
               for constraint in FtaRecurrence.__table__.constraints)


def test_fta_related_investigation_requires_positive_template_id():
    from pydantic import ValidationError
    from app.api.fta import RelatedInvestigationCreate

    payload = RelatedInvestigationCreate(template_id=7, summary="Separate root cause review")
    assert payload.template_id == 7
    with pytest.raises(ValidationError):
        RelatedInvestigationCreate(template_id=0)



def test_fta_recurrence_request_schemas_require_reasons_and_quality_decision():
    from pydantic import ValidationError
    from app.api.fta import RecurrenceCreate, RecurrenceReview

    with pytest.raises(ValidationError):
        RecurrenceCreate(rejection_id=0, recurrence_reason="short")
    with pytest.raises(ValidationError):
        RecurrenceCreate(rejection_id=9, recurrence_reason="no")
    created = RecurrenceCreate(
        rejection_id=9,
        recurrence_reason="Repeated thread damage observed during final inspection",
        containment_action="Segregate current lot",
        new_evidence="Inspection photo set 9",
    )
    assert created.rejection_id == 9
    with pytest.raises(ValidationError):
        RecurrenceReview(classification="PENDING_REVIEW", review_remarks="Waiting")
    reviewed = RecurrenceReview(
        classification="SAME_ROOT_CAUSE",
        review_remarks="Confirmed against the previous FTA evidence and action history.",
    )
    assert reviewed.classification == "SAME_ROOT_CAUSE"
