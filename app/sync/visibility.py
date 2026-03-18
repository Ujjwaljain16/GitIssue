def can_surface(rep: dict, context: str, org: str) -> bool:
    visibility = (rep.get("visibility") or "private").lower()
    rep_org = rep.get("org_id")
    source = (rep.get("source") or "").lower()

    if visibility == "public":
        return True

    if visibility == "internal":
        return rep_org is not None and rep_org == org

    # private
    return context.lower().startswith(source)
