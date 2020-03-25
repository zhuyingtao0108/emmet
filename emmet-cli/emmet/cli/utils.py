import os
import logging
import itertools

from collections import defaultdict
from log4mongo.handlers import MongoFormatter
from fireworks import LaunchPad
from atomate.vasp.database import VaspCalcDb
from pymatgen import Structure
#from emmet.vasp.materials import group_structures
from mongogrant.client import Client


exclude = {'about.remarks': {'$nin': ['DEPRECATED', 'deprecated']}}
skip_labels = ['He', 'He0+', 'Ar', 'Ar0+', 'Ne', 'Ne0+', 'D', 'D+', 'T', 'M']
base_query = {'is_ordered': True, 'is_valid': True, 'nsites': {'$lt': 200}, 'sites.label': {'$nin': skip_labels}}
aggregation_keys = ['formula_pretty', 'reduced_cell_formula']
structure_keys = ['snl_id', 'lattice', 'sites', 'charge', 'about._materialsproject.task_id']


def get_lpad():
    if 'FW_CONFIG_FILE' not in os.environ:
        raise ValueError('FW_CONFIG_FILE not set!')
    return LaunchPad.auto_load()


#def structures_match(s1, s2):
#    return bool(len(list(group_structures([s1, s2]))) == 1)


def ensure_indexes(indexes, colls):
    created = defaultdict(list)
    for index in indexes:
        for coll in colls:
           keys = [k.rsplit('_', 1)[0] for k in coll.index_information().keys()]
           if index not in keys:
               coll.ensure_index(index)
               created[index].append(coll.full_name)
    return created


class MyMongoFormatter(logging.Formatter):
    KEEP_KEYS = ['timestamp', 'level', 'message', 'formula', 'snl_id', 'tags', 'error', 'canonical_snl_id', 'fw_id', 'task_id', 'task_id(s)']
    mongoformatter = MongoFormatter()

    def format(self, record):
        document = self.mongoformatter.format(record)
        for k in list(document.keys()):
            if k not in self.KEEP_KEYS:
                document.pop(k)
        return document


def calcdb_from_mgrant(spec):
    client = Client()
    role = 'rw' # NOTE need write access to source to ensure indexes
    host, dbname_or_alias = spec.split('/', 1)
    auth = client.get_auth(host, dbname_or_alias, role)
    if auth is None:
        raise Exception("No valid auth credentials available!")
    return VaspCalcDb(
        auth['host'], 27017, auth['db'],
        'tasks', auth['username'], auth['password'],
        authSource=auth['db']
    )


def get_meta_from_structure(struct):
    d = {'formula_pretty': struct.composition.reduced_formula}
    d['nelements'] = len(set(struct.composition.elements))
    d['nsites'] = len(struct)
    d['is_ordered'] = struct.is_ordered
    d['is_valid'] = struct.is_valid()
    return d


def ensure_meta(snl_coll):
    """ensure meta-data fields and index are set in SNL collection"""

    meta_keys = ['formula_pretty', 'nelements', 'nsites', 'is_ordered', 'is_valid']
    q = {'$or': [{k: {'$exists': 0}} for k in meta_keys]}
    docs = snl_coll.find(q, structure_keys)

    if docs.count() > 0:
      print('fix meta for', docs.count(), 'SNLs ...')
      for idx, doc in enumerate(docs):
          if idx and not idx%1000:
              print(idx, '...')
          struct = Structure.from_dict(doc)
          snl_coll.update({'snl_id': doc['snl_id']}, {'$set': get_meta_from_structure(struct)})

    ensure_indexes([
      'snl_id', 'reduced_cell_formula', 'formula_pretty', 'about.remarks', 'about.projects',
      'sites.label', 'nsites', 'nelements', 'is_ordered', 'is_valid'
    ], [snl_coll])


def aggregate_by_formula(coll, q, key=None):
    query = {'$and': [q, exclude]}
    query.update(base_query)
    if key is None:
        for k in aggregation_keys:
            q = {k: {'$exists': 1}}
            q.update(base_query)
            if coll.count(q):
                key = k
                break
        else:
            raise ValueError('could not find aggregation keys', aggregation_keys, 'in', coll.full_name)
    return coll.aggregate([
        {'$match': query}, {'$sort': {'nelements': 1, 'nsites': 1}},
        {'$group': {
            '_id': f'${key}',
            'structures': {'$push': dict((k.split('.')[-1], f'${k}') for k in structure_keys)}
        }}
    ], allowDiskUse=True, batchSize=1)


# a utility function to get us a slice of an iterator, as an iterator
# when working with iterators maximum lazyness is preferred
def iterator_slice(iterator, length):
    iterator = iter(iterator)
    while True:
        res = tuple(itertools.islice(iterator, length))
        if not res:
            break
        yield res


def get_subdir(dn):
    return dn.rsplit(os.sep, 1)[-1]
