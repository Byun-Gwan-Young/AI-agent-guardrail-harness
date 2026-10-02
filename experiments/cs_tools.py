"""Local tools of the customer-support task (DEMO-CS, C-17-6 part 1): lookup_order and read_policy.

Both only read the scenario's inputs_dir (demo-runner-extension.md 5); nothing is written and nothing outside it is
read. File formats (decision 018; C-18 writes the real CS inputs in them):
- orders.json : a JSON object {"orders": [...]}; every order is a JSON object whose "order_id" is a non-empty string,
  unique in the file. The other fields are free JSON and are returned as they are.
- policies/<name>.md : UTF-8 text. The document name is the file stem: lowercase ASCII letters, digits, '_' or '-',
  starting with a letter or digit. There is no listing call (the design has none); an unknown name gets an error
  result that states the document names.
"""
import hashlib
import json
from pathlib import Path
import re

from experiments.tool_results import Result, ToolFactError

TOOLS = ('lookup_order', 'read_policy')
ORDERS_FILE = 'orders.json'
POLICY_DIR = 'policies'
POLICY_SUFFIX = '.md'
POLICY_NAME = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
# How read_policy may name a document: "refund", "refund.md", "policies/refund.md".
NAME_FORMS = (('', ''), ('', POLICY_SUFFIX), (POLICY_DIR + '/', POLICY_SUFFIX))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_orders(inputs_dir):
    """(orders, sha256 of orders.json). ValueError when the file breaks the format."""
    path = Path(inputs_dir) / ORDERS_FILE
    data = path.read_bytes()
    try:
        value = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(ORDERS_FILE + ' is not UTF-8 JSON: ' + type(exc).__name__) from exc
    if not isinstance(value, dict) or set(value) != {'orders'} or not isinstance(value['orders'], list):
        raise ValueError(ORDERS_FILE + ' must be an object with the one key "orders" holding a list')
    ids = []
    for order in value['orders']:
        if not isinstance(order, dict) or not isinstance(order.get('order_id'), str) or not order['order_id'].strip():
            raise ValueError(ORDERS_FILE + ': every order is an object with a non-empty string order_id')
        ids.append(order['order_id'])
    if len(ids) != len(set(ids)):
        raise ValueError(ORDERS_FILE + ': order_id values must be unique')
    return value['orders'], sha256(data)


def policy_documents(inputs_dir):
    """{name: path} of the policy documents. A file that resolves outside inputs_dir (a link) is not a document."""
    root = Path(inputs_dir).resolve()
    folder = Path(inputs_dir) / POLICY_DIR
    if not folder.is_dir():
        return {}
    return {p.name[:-len(POLICY_SUFFIX)]: p for p in sorted(folder.iterdir())
            if p.name.endswith(POLICY_SUFFIX) and POLICY_NAME.match(p.name[:-len(POLICY_SUFFIX)])
            and p.is_file() and p.resolve().is_relative_to(root)}


def input_problems(tool, inputs_dir):
    """What keeps the tool from working on these inputs; checked before a run (C-17-6 part 3). Empty when fine."""
    inputs_dir = Path(inputs_dir)
    if not inputs_dir.is_dir():
        return ['inputs_dir not found']
    if tool == 'lookup_order':
        if not (inputs_dir / ORDERS_FILE).is_file():
            return [ORDERS_FILE + ' not found']
        try:
            load_orders(inputs_dir)
        except (OSError, ValueError) as exc:
            return [str(exc)]
        return []
    if tool == 'read_policy':
        folder = inputs_dir / POLICY_DIR
        if not folder.is_dir():
            return [POLICY_DIR + '/ not found']
        problems = [POLICY_DIR + '/' + p.name + ' is not a policy document (name or location)'
                    for p in sorted(folder.iterdir()) if p.name.endswith(POLICY_SUFFIX)
                    and p.name[:-len(POLICY_SUFFIX)] not in policy_documents(inputs_dir)]
        return problems or ([] if policy_documents(inputs_dir) else [POLICY_DIR + '/ has no policy document'])
    raise ValueError('not a local CS tool: ' + tool)


def lookup_order(arguments, context):
    order_id = arguments.get('order_id')
    if not isinstance(order_id, str) or not order_id.strip():
        raise ToolFactError('lookup_order needs order_id as a non-empty string.')
    orders, digest = load_orders(context['inputs_dir'])
    source = {'source': {'file': ORDERS_FILE, 'sha256': digest}}
    for order in orders:
        if order['order_id'] == order_id:
            return Result(order, source)
    raise ToolFactError('No order with order_id ' + json.dumps(order_id, ensure_ascii=False) + ' in the order data.',
                        source)


def requested_name(name):
    """The document name asked for: "refund", "refund.md" or "policies/refund.md". Anything else (other paths,
    "..", absolute paths) names no document."""
    if not isinstance(name, str):
        return None
    for head, tail in NAME_FORMS:
        if name.startswith(head) and name.endswith(tail) and len(name) > len(head) + len(tail):
            stem = name[len(head):len(name) - len(tail)]
            if POLICY_NAME.match(stem):
                return stem
    return None


def read_policy(arguments, context):
    name = arguments.get('name')
    documents = policy_documents(context['inputs_dir'])
    stem = requested_name(name)
    if stem not in documents:
        raise ToolFactError('No policy document named ' + json.dumps(name, ensure_ascii=False) + '. '
                            'read_policy reads only the policy documents of the task: '
                            + (', '.join(documents) if documents else 'none') + '.')
    data = documents[stem].read_bytes()
    return Result(data.decode('utf-8'), {'source': {'file': POLICY_DIR + '/' + documents[stem].name,
                                                    'sha256': sha256(data)}})
