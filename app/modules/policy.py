from app.business import decision


def policy(result):
    return decision(result,'ENTITY_COUNT_MISMATCH' if result['value']!=result['expected'] else None)
