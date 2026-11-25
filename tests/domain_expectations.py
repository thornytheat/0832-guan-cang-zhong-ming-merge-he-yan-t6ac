EXPECTED = {'0001': (3, 2, 'READY'),
 '0002': (3, 2, 'READY'),
 '0003': (0, None, 'UNKNOWN_AUTHOR'),
 '0004': (2, 2, 'ENTITY_COUNT_MISMATCH')}
EVIDENCE = {'0001': {'clusters': {'1': [1, 2], '3': [3]},
          'blocked': {'2:3': 'AUTHORITY_CONFLICT'}},
 '0002': {'clusters': {'1': [1, 2], '3': [3]},
          'blocked': {'2:3': 'CANNOT_LINK'}}}
