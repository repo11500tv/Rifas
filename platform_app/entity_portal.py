from flask import Blueprint, render_template, abort
from platform_app.entity_routes import get_entity

entity_portal_bp = Blueprint("entity_portal", __name__)


@entity_portal_bp.get("/e/<slug>/")
def home(slug):
    entity = get_entity(slug)

    if not entity:
        abort(404)

    if isinstance(entity, dict):
        name = (
            entity.get("name")
            or entity.get("display_name")
            or slug
        )
    else:
        try:
            name = entity["name"]
        except (KeyError, IndexError, TypeError):
            name = slug

    return render_template(
        "entity_portal.html",
        slug=slug,
        entity_name=name,
    )
