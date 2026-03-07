"""Label ID/name mapping utilities."""
from typing import Dict, List, Tuple


def build_label_mapping(labels: List[dict]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Build bidirectional label ID<->name mapping.

    Args:
        labels: List of label dicts with 'id' and 'name' keys

    Returns:
        Tuple of (id_to_name, name_to_id) dictionaries

    Example:
        labels = [{"id": "L1", "name": "inbox"}, {"id": "L2", "name": "sent"}]
        id_to_name, name_to_id = build_label_mapping(labels)
        # id_to_name = {"L1": "inbox", "L2": "sent"}
        # name_to_id = {"inbox": "L1", "sent": "L2"}
    """
    id_to_name = {
        str(label.get("id", "")): str(label.get("name", "") or "")
        for label in labels
        if label.get("id")
    }
    name_to_id = {name: lid for lid, name in id_to_name.items() if name}
    return id_to_name, name_to_id
