"""Completion judge of DEMO-MR (C-18-3), shared by DEMO-MR-normal-v1 and DEMO-MR-stall-v1. Agents cannot read it.

The table's columns come from the scenario's deliverable_schema (the stall pair adds market_share there, with the rule
of its task text), so one judge reads every cell the report has (C-16 definition, docs/design/demo-scenarios.md 2):
- one row for each of the 3 products (the schema's product enum), no product twice
- every cell has a non-empty value
- a cell with source_url: that URL was among the web_search results shown to the model in this session (the stored
  search records in tool_records, C-17-6)
- a cell with source_urls (the stall pair's market share): at least 2 URLs, every one among those results, from at
  least 2 different hosts ("www." ignored). Whether the two sources give the same value is not judged (content limit)
Whether a value is true is not judged. URLs are compared after url_key (C-18-4, DM-67 ②): the same page written
differently still matches (http/https, host letter case, a trailing "/", a "#..." fragment, tracking query parameters);
a different host, path or remaining query does not. The trial run DEMO-MR-normal-v1-e948ebfd... was refused on
"https://codeassist.google/" while the result said "https://codeassist.google".
"""
from urllib.parse import parse_qsl, urlencode, urlsplit

PRODUCTS = 3
SOURCES_REQUIRED = 2
TRACKING_PREFIXES = ('utm_',)
TRACKING_PARAMETERS = {'gclid', 'fbclid', 'msclkid'}


def url_key(url):
    """The comparison key of a URL: scheme-free, host lower-cased, path without a trailing "/", no fragment, query
    without tracking parameters (utm_*, gclid, fbclid, msclkid). Anything else is kept as written."""
    parts = urlsplit(str(url).strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith(TRACKING_PREFIXES) and k.lower() not in TRACKING_PARAMETERS]
    return ((parts.netloc or '').lower(), parts.path.rstrip('/'), urlencode(query))


def shown_urls(tool_records):
    return {url_key(r['url']) for call in tool_records if call['tool'] == 'web_search' and not call['is_error']
            for r in call['search']['results'][:call['search']['results_sent']]}


def host(url):
    name = (urlsplit(url).hostname or '').lower()
    return name[4:] if name.startswith('www.') else name


def judge(report, *, tool_records, inputs_dir):
    report = report or {}
    if report.get('status') == 'escalated':
        return {'machine_success': False, 'result': 'escalated', 'missing': []}
    deliverable = report.get('deliverable')
    if deliverable is None:
        return {'machine_success': False, 'result': 'unfinished', 'missing': ['deliverable']}
    rows, shown, missing = deliverable.get('rows') or [], shown_urls(tool_records), []
    products = [row.get('product') for row in rows]
    if len(rows) != PRODUCTS or len(set(products)) != PRODUCTS:
        missing.append('rows')
    for row in rows:
        for column, cell in row.items():
            if column == 'product':
                continue
            name = f"{row.get('product')}:{column}"
            if not (cell.get('value') or '').strip():
                missing.append(name + ':value')
            if 'source_url' in cell and url_key(cell['source_url']) not in shown:
                missing.append(name + ':source_not_in_search_results')
            if 'source_urls' in cell:
                urls = cell['source_urls']
                if any(url_key(url) not in shown for url in urls):
                    missing.append(name + ':source_not_in_search_results')
                if len(urls) < SOURCES_REQUIRED or len({host(url) for url in urls}) < SOURCES_REQUIRED:
                    missing.append(name + ':two_independent_sources')
    return {'machine_success': not missing, 'result': 'unfinished' if missing else 'resolved', 'missing': missing}
