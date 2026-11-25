from app.business import measured


def compute(data):
    authority, links, exclusions, audit = data
    membership = {key:key for key in authority}
    members = {key:{key} for key in authority}
    trusted = {key:authority[key] for key in authority}
    banned = {key:set() for key in authority}
    for a,b in exclusions:
        banned[a].add(b)
        banned[b].add(a)

    def join(a,b):
        x,y = sorted((membership[a],membership[b]))
        if x==y:
            return None
        if trusted[x] and trusted[y] and trusted[x]!=trusted[y]:
            return 'AUTHORITY_CONFLICT'
        if banned[x].intersection(members[y]):
            return 'CANNOT_LINK'
        for key in members[y]:
            membership[key]=x
        members[x].update(members.pop(y))
        banned[x].update(banned.pop(y))
        other_id = trusted.pop(y)
        trusted[x] = trusted[x] or other_id
        return None

    authoritative = {}
    for key,identifier in sorted(authority.items()):
        if identifier:
            join(key,authoritative.setdefault(identifier,key))
    blocked = {}
    for (a,b),score in sorted(links.items(),key=lambda item:(-item[1],item[0])):
        if score < audit['similarity']:
            continue
        reason = join(a,b)
        if reason:
            blocked[f'{a}:{b}'] = reason
    return measured(len(members),audit['permitted'],'组',{'clusters':{str(k):sorted(v) for k,v in sorted(members.items())},'blocked':blocked})
