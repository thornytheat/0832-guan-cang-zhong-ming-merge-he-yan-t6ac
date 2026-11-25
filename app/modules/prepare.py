from app.business import DomainIssue, by_kind, prepared, single


def prepare(rows):
    audit = single(rows,'audit')
    people = by_kind(rows,'name')
    authority = {r['author']:r['authority'] for r in people}
    if not people or len(authority)!=len(people) or 0 in authority or not 1<=audit['similarity']<=100:
        raise DomainIssue('INVALID_REGISTER')
    links, exclusions = {}, set()
    for row in rows:
        kind = row['kind']
        if kind not in {'link','cannot'}:
            continue
        a,b = sorted((row['author'],row['peer']))
        if a not in authority or b not in authority or a==b:
            raise DomainIssue('UNKNOWN_AUTHOR')
        if kind=='cannot':
            exclusions.add((a,b))
        elif not 1<=row['similarity']<=100:
            raise DomainIssue('INVALID_SIMILARITY')
        else:
            links[a,b]=max(links.get((a,b),0),row['similarity'])
    if any(authority[a] and authority[a]==authority[b] for a,b in exclusions):
        raise DomainIssue('AUTHORITY_EXCLUSION_CONFLICT')
    return prepared(len(people),{'links':len(links),'cannot_link':len(exclusions)},(authority,links,exclusions,audit))
