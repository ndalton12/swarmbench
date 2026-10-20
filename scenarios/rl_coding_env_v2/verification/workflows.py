"""Author-only workflow contracts, related mutation sets and case inputs."""

from primitive_mutations import DEFECTS as OLD_DEFECTS
from primitive_mutations import SPECS as PRIMITIVES

BY_FUNCTION = {(s["library"], s["function"]): s for s in PRIMITIVES}
WORKFLOWS = []


def workflow(title, library, functions, body, issue, cases):
    WORKFLOWS.append(
        {
            "title": title,
            "library": library,
            "functions": functions.split(),
            "body": body,
            "issue": issue,
            "inputs": cases,
        }
    )


names = [
    "HTTPUser_identifier_id",
    "APIResponse_identity_id",
    "XMLAccount_id_number",
    "JSONOrder_identifier_id",
    "HTTPServer_grid_id_code",
    "CSVImport_identity_id",
    "APIUser_id_token",
    "XMLContact_identifier_id",
    "HTTPDevice_identity_id",
    "JSONInvoice_id_number",
    "CSVRecord_identifier_id",
    "APIEvent_identity_id",
    "HTTPMetric_id_label",
    "XMLProject_identity_id",
    "JSONAccount_identifier_id",
    "APIRecord_id_number",
    "HTTPEntry_identity_id",
    "XMLItem_identifier_id",
    "JSONMember_id_code",
    "CSVUser_identity_id",
    "HTTPReport_identifier_id",
    "APIField_id_number",
    "XMLBilling_identity_id",
    "JSONSchema_identifier_id",
    "HTTPList_id_label",
    "CSVExport_identity_id",
    "APIModel_identifier_id",
    "XMLDevice_id_number",
    "HTTPGroup_identity_id",
    "JSONColumn_identifier_id",
]
workflow(
    "Schema registry names and display labels",
    "inflection",
    "camelize underscore humanize",
    "canonical = m.underscore(data)\nresult = {'key': m.camelize(canonical, False), 'label': m.humanize(canonical)}",
    "The schema registry now publishes identifiers containing separators and its display labels lose parts of their names. The key and label describe the same field: identifiers must use lower camel case, while labels keep embedded identifier words and omit only a trailing metadata suffix. Acronyms in existing schema names still need ordinary word boundaries.",
    names,
)
workflow(
    "Import wizard column headings",
    "inflection",
    "humanize underscore titleize",
    "canonical = m.underscore(data)\nresult = {'heading': m.titleize(data), 'caption': m.humanize(canonical)}",
    "The import wizard shows joined words in headings and abbreviated captions for some exported columns. Its two views should describe the same complete field name, with a title-style heading and a sentence-style caption. Mixed acronym names and embedded identity words must survive the rendering.",
    names[3:] + names[:3],
)
workflow(
    "Ranked archive route generation",
    "inflection",
    "ordinal ordinalize parameterize",
    "label = 'position ' + m.ordinalize(data)\nresult = {'label': label, 'route': m.parameterize(label, separator='.')} ",
    "Archive entries disagree between their visible rank and their URL. Negative positions must retain their sign, including teen positions, and the URL must retain the rank words with literal dot separators. The route is derived from the displayed rank, not a separate numbering system.",
    [
        -x
        for x in [
            11,
            12,
            13,
            111,
            112,
            113,
            211,
            212,
            213,
            311,
            312,
            313,
            411,
            412,
            413,
            511,
            512,
            513,
            611,
            612,
            613,
            711,
            712,
            713,
            811,
            812,
            813,
            911,
            912,
            913,
        ]
    ],
)
workflow(
    "Signed report section links",
    "inflection",
    "ordinalize parameterize dasherize",
    "section = m.dasherize(data['section'])\nresult = m.parameterize(section + ' ' + m.ordinalize(data['rank']), separator='+')",
    "Links to signed report sections have started pointing to different sections. Every underscore in the section identifier belongs to the section path, the rank retains its sign, and punctuation between the section and rank is represented by a literal plus separator. Existing section components must not disappear.",
    [{"section": f"account_line_{i}_item", "rank": -21 - i * 10} for i in range(30)],
)
workflow(
    "Localized catalog labels and slugs",
    "inflection",
    "parameterize transliterate humanize",
    "label = m.humanize(m.transliterate(data))\nresult = {'label': label, 'slug': m.parameterize(label, separator='+')}",
    "Localized catalog fields lose letters in their labels and collapse to empty or shortened slugs. Both outputs should retain ASCII approximations of supported accented text, retain embedded identifier words, and agree on the field being represented. Slugs use literal plus separators.",
    [
        f"{x}_identifier_{i}_id"
        for i, x in enumerate(["résumé", "Málaga", "naïve", "élève", "café", "ﬂower"] * 5)
    ],
)
workflow(
    "Resource registry aliases",
    "inflection",
    "pluralize camelize underscore",
    "parts = [m.pluralize(part) for part in data]\nresult = m.camelize(m.underscore('_'.join(parts)), False)",
    "Resource aliases now gain unexpected suffixes and sometimes expose internal separators. An alias combines the plural resource words into one lower-camel identifier. Uncountable names keep their spelling, and acronym-bearing component names remain separate words.",
    [[["EQUIPMENT", "INFORMATION", "RICE"][i % 3], f"HTTPGroup{i}Person"] for i in range(30)],
)
workflow(
    "Resource name normalization for endpoint paths",
    "inflection",
    "singularize underscore dasherize",
    "result = m.dasherize(m.underscore(m.singularize(data)))",
    "Endpoint paths derived from imported resource names no longer match the singular resource labels. The path must represent the singular form in lowercase dash-separated words, including acronym boundaries and all separator positions. Names merely ending in letters from another noun still need normal inflection.",
    [f"{prefix}Group{i}Bluejeans" for i, prefix in enumerate(["HTTP", "XML", "JSON", "API", "CSV"] * 6)],
)
workflow(
    "Model-to-collection registration",
    "inflection",
    "tableize camelize pluralize",
    "table = m.tableize(data)\nresult = {'table': table, 'collection': m.camelize(table, False)}",
    "The model registry disagrees with its collection names after importing compound model names. Tables use plural snake-case names; collection identifiers are the corresponding lower-camel spelling of those table names. Existing irregular resource nouns should retain their documented forms.",
    [
        f"{prefix}{i}Person"
        for i, prefix in enumerate(["Business", "Sales", "Support", "Billing", "Contact"] * 6)
    ],
)
workflow(
    "Search-result title rendering",
    "inflection",
    "titleize humanize transliterate",
    "result = m.titleize(m.transliterate(data))",
    "Search results show internal name boundaries and lose words after localization. A rendered title should keep the complete field identity while producing readable title-cased words and supported ASCII approximations. Existing compound names and embedded identity words are valid inputs.",
    [
        f"{prefix}Réponse_identifier_{i}_id"
        for i, prefix in enumerate(["HTTP", "API", "XML", "JSON", "CSV"] * 6)
    ],
)
workflow(
    "Portable route key export",
    "inflection",
    "transliterate underscore parameterize",
    "key = m.underscore(m.transliterate(data))\nresult = m.parameterize(key.replace('_', ' '), separator='+')",
    "Portable route keys no longer identify the same records as their source names. Preserve supported ASCII approximations and word boundaries before emitting a lowercase plus-separated key. Acronyms and localized words can occur together in one name.",
    [f"{prefix}RéponseRésumé{i}Item" for i, prefix in enumerate(["HTTP", "XML", "JSON", "API", "CSV"] * 6)],
)
workflow(
    "Administrative resource descriptions",
    "inflection",
    "underscore pluralize humanize",
    "raw = '_'.join(m.pluralize(part) for part in data)\nresult = m.humanize(m.underscore(raw))",
    "Administrative descriptions add suffixes to uncountable resource names and omit identity words from compound labels. A description joins the plural resource components into one sentence-style label without losing the identity of any component or its acronym boundaries.",
    [[["EQUIPMENT", "INFORMATION", "RICE"][i % 3], f"HTTPUser{i}_identifier_id"] for i in range(30)],
)
workflow(
    "Database migration filename generation",
    "inflection",
    "dasherize tableize underscore",
    "result = m.dasherize(m.tableize(data))",
    "Generated migration filenames no longer match their target table names. A filename is the dash-separated spelling of the plural snake-case table name, including all words in compound acronym-bearing model names. Different naming surfaces must identify the same table.",
    [f"{prefix}Server{i}CacheEntry" for i, prefix in enumerate(["HTTP", "XML", "JSON", "API", "CSV"] * 6)],
)

rows = lambda i: [
    {"group": "A", "value": i + 2},
    {"group": "B", "value": i + 5},
    {"group": "a", "value": i + 9},
    {"group": "C"},
    {"group": "b", "value": i + 1},
]
workflow(
    "First-seen grouped projection export",
    "toolz",
    "unique pluck",
    "projected = m.pluck(['group', 'value'], data, default=0)\nresult = list(m.unique(projected, key=lambda row: row[0].lower()))",
    "The grouped projection export repeats logical groups and assigns the wrong values to columns. The first complete projected row for each case-insensitive group is retained, in source order. Missing value fields use zero; the group and value columns have distinct meanings.",
    [rows(i) for i in range(30)],
)
workflow(
    "Rolling adjustment ledger",
    "toolz",
    "accumulate sliding_window",
    "deltas = (right-left for left,right in m.sliding_window(2, data['readings']))\nresult = list(m.accumulate(operator.sub, deltas, data['opening']))",
    "Rolling adjustment ledgers drift after a sequence of readings even though the opening balance is correct. Each adjacent reading contributes one change and the ledger subtracts those changes in reading order. A one-shot reading stream must yield the same balances as a stored sequence.",
    [{"readings": [i + 10, i + 16, i + 13, i + 20, i + 19], "opening": 100 + i} for i in range(30)],
)
workflow(
    "Multiplexed transport frames",
    "toolz",
    "interleave partition_all",
    "merged = list(m.interleave(iter(stream) for stream in data['streams']))\nresult = list(m.partition_all(data['size'], merged))",
    "Transport frames reorder or lose events when channels end at different times. Channels contribute in round-robin order while active, and frames retain the entire merged stream, including a final partial frame. An exhausted channel must not discard another channel’s remaining events.",
    [
        {"streams": [[i, i + 1, i + 2, i + 3], [], [100 + i], [200 + i, 201 + i]], "size": 3 + (i % 2)}
        for i in range(30)
    ],
)
workflow(
    "Recent multiplexed event window",
    "toolz",
    "tail interleave",
    "result = m.tail(data['count'], m.interleave(iter(stream) for stream in data['streams']))",
    "The recent-event panel shows the wrong events after a short channel closes. Its bounded history is the final part of the complete round-robin stream, without losing events from longer channels. Empty channels and uneven lengths are ordinary inputs.",
    [
        {"streams": [[i + j for j in range(6)], [], [100 + i, 101 + i], [200 + i]], "count": 3 + (i % 2)}
        for i in range(30)
    ],
)
workflow(
    "Projected row selection API",
    "toolz",
    "get pluck",
    "projected = list(m.pluck(['group','value'], data['rows'], default=0))\nresult = m.get([data['index']], projected)",
    "The projected-row selection API changes its response shape for a single requested row and returns repeated columns. A list of requested row positions always produces a sequence of rows, even for one position. Each row preserves the requested group/value column order and default values.",
    [{"rows": rows(i), "index": i % 5} for i in range(30)],
)
workflow(
    "Delimited batch archive writer",
    "toolz",
    "interpose partition_all",
    "frames = m.partition_all(data['size'], data['items'])\nresult = list(m.interpose(['boundary'], frames))",
    "Batch archives omit their first frame and mishandle the last partial frame. The archive contains every frame in order, with one boundary record only between frames. No input item may vanish because the batch size does not divide the input length.",
    [{"items": list(range(i, i + 7 + (i % 3))), "size": 3 + (i % 2)} for i in range(30)],
)
workflow(
    "Case-insensitive frequency summary",
    "toolz",
    "frequencies unique",
    "counts = m.frequencies(word.lower() for word in data)\nannotated = [(word, counts[word.lower()]) for word in data]\nresult = list(m.unique(annotated, key=lambda row: row[0].lower()))",
    "Frequency summaries report one occurrence for repeated words and emit the same logical word more than once. Counts are case-insensitive across the full input; the exported summary retains the first spelling and first-seen order of each word.",
    [[f"A{i}", f"B{i}", f"a{i}", f"C{i}", f"b{i}", f"A{i}"] for i in range(30)],
)
workflow(
    "Weighted outer-join account ledger",
    "toolz",
    "reduceby join",
    "pairs = list(m.join(0, map(tuple,data['entries']), 0, map(tuple,data['weights']), left_default=None, right_default=None))\nkey = lambda pair: pair[0][0] if pair[0] is not None else pair[1][0]\namount = lambda pair: (pair[0][1] if pair[0] is not None else 0) * (pair[1][1] if pair[1] is not None else 1)\ntotals = m.reduceby(key, lambda total,pair: total+amount(pair), pairs, 0)\nmembers = m.reduceby(key, lambda group,pair: (group.append(pair) or group), pairs, list)\nresult = {'totals': totals, 'members': members}",
    "The weighted account ledger duplicates matched entries, drops first contributions, and mixes audit rows between accounts. Totals and audit membership must describe the same outer join: unmatched entries retain unit weight, missing entries contribute zero, and every account gets its own audit list.",
    [
        {
            "entries": [["A", i + 2], ["B", i + 3], ["A", i + 4], ["C", i + 5]],
            "weights": [["A", 2], ["B", 3], ["D", 4]],
        }
        for i in range(30)
    ],
)
workflow(
    "Lookahead-based rolling reader",
    "toolz",
    "sliding_window peekn",
    "preview, replay = m.peekn(data['preview'], iter(data['items']))\nresult = {'preview': preview, 'windows': list(m.sliding_window(data['width'], replay))}",
    "Rolling readers behave differently after requesting a preview. Previewing must not remove input from the reader’s later windows, and windows represent consecutive positions in the original stream. Long and short previews should preserve the same underlying input.",
    [{"items": list(range(i, i + 8)), "preview": 1 + i % 4, "width": 2 + i % 3} for i in range(30)],
)
workflow(
    "Previewed batch delivery",
    "toolz",
    "partition_all peekn",
    "preview, replay = m.peekn(data['preview'], iter(data['items']))\nresult = {'preview': preview, 'frames': list(m.partition_all(data['size'], replay))}",
    "Batch delivery loses previewed records and trims partial frames. A preview is informational; delivery must still include every original record exactly once, in order, with the last frame allowed to be shorter. Preview length and frame size are independent settings.",
    [{"items": list(range(i, i + 7 + (i % 3))), "preview": 1 + i % 3, "size": 3 + i % 2} for i in range(30)],
)
workflow(
    "Projected group totals and membership",
    "toolz",
    "pluck reduceby",
    "projected = list(m.pluck(['group','value'], data, default=0))\ntotals = m.reduceby(0, lambda total,row: total+row[1], projected, 0)\nmembers = m.reduceby(0, lambda group,row: (group.append(row) or group), projected, list)\nresult = {'totals': totals, 'members': members}",
    "Group exports disagree between their projected rows, totals and membership lists. Projection must keep distinct field values, every row contributes once to its group total, and membership lists remain independent even when groups are interleaved in the source.",
    [rows(i) for i in range(30)],
)
workflow(
    "First-record reconciliation join",
    "toolz",
    "join unique",
    "left = m.unique(map(tuple,data['entries']), key=lambda row: row[0])\nresult = list(m.join(0, left, 0, map(tuple,data['lookup']), right_default=None))",
    "Reconciliation emits repeated logical entries and marks already matched entries as unmatched. The first input row for each key is authoritative. It participates in every legitimate lookup match, while only keys absent from the lookup receive a missing-partner record.",
    [
        {
            "entries": [["A", i + 1], ["B", i + 2], ["A", i + 9], ["C", i + 3], ["B", i + 8]],
            "lookup": [["A", "x"], ["B", "y"], ["A", "z"]],
        }
        for i in range(30)
    ],
)
workflow(
    "Frequency-ranked activity digest",
    "toolz",
    "topk frequencies",
    "counts = m.frequencies(data['items'])\nresult = m.topk(data['count'], counts.items(), key=lambda row: (row[1], row[0]))",
    "The activity digest promotes rare events and loses repeated activity counts. Rankings are descending by occurrence count, then descending identifier for ties. Counts cover the complete input and the digest contains at most the requested number of distinct events.",
    [
        {"items": [f"A{i}", f"B{i}", f"A{i}", f"C{i}", f"A{i}", f"B{i}", f"D{i}"], "count": 2 + i % 2}
        for i in range(30)
    ],
)
workflow(
    "Preview and trailing-history reconciliation",
    "toolz",
    "peekn tail",
    "preview, replay = m.peekn(data['preview'], iter(data['items']))\nreceived = list(replay)\nresult = {'preview': preview, 'received': len(received), 'recent': m.tail(data['count'], iter(received))}",
    "The history view no longer reconciles its preview, received count and recent items. Requesting a preview must not alter the delivered stream. The received count covers that full stream, and the recent view contains its last requested items rather than its beginning.",
    [{"items": list(range(i, i + 9)), "preview": 2 + i % 3, "count": 3 + i % 2} for i in range(30)],
)

workflow(
    "Striped strict transport framing",
    "more_itertools",
    "chunked distribute",
    "channels = m.distribute(data['channels'], iter(data['items']))\nresult = [None] * data['channels']\nfor index in data['order']:\n    result[index] = list(m.chunked(channels[index], data['size'], strict=True))",
    "Striped transport frames depend on which channel is read first, and incomplete frames sometimes escape strict validation. Each source position belongs to one round-robin channel independent of consumption order. Every emitted frame must have the configured width, with incomplete input rejected.",
    [
        {
            "items": list(range(i, i + 12 + (i % 2))),
            "channels": 2,
            "size": 3,
            "order": [1, 0] if i % 3 else [0, 1],
        }
        for i in range(30)
    ],
)
workflow(
    "Stepped windows of telemetry changes",
    "more_itertools",
    "windowed difference",
    "changes = m.difference(data['readings'])\nresult = list(m.windowed(changes, data['width'], step=data['step'], fillvalue=0))",
    "Telemetry windows show reversed changes and sometimes create frames with no source anchor or too little padding. Changes preserve the first reading and then measure current minus previous. Windows are anchored in that change stream, with only the necessary final padding.",
    [
        {"readings": [i + 10, i + 17, i + 22, i + 25][: 1 + i % 4], "width": 2 + i % 3, "step": 3 + i % 3}
        for i in range(30)
    ],
)
workflow(
    "Escaped-delimiter record splitting",
    "more_itertools",
    "split_at replace",
    "tokens = m.replace(data, lambda a,b: a=='escape' and b==',', ['literal-comma'], window_size=2)\nresult = list(m.split_at(tokens, lambda item:item==',', maxsplit=1))",
    "The record splitter loses text after escaped delimiters and reintroduces delimiters into the unsplit remainder. Escaped comma pairs become literal comma tokens; the first remaining comma separates records and is excluded. Later commas remain ordinary content in the unsplit tail.",
    [
        ["head" + str(i), "escape", ",", "middle" + str(i), ",", "tail" + str(i), ",", "end"]
        for i in range(30)
    ],
)
workflow(
    "Consecutive ranges in threshold batches",
    "more_itertools",
    "split_before consecutive_groups",
    "ranges = [list(group) for group in m.consecutive_groups(data['items'], ordering=int)]\nresult = list(m.split_before(ranges, lambda group:int(group[0])>=data['threshold'], maxsplit=1))",
    "Range batches fragment consecutive identifiers and omit the range that starts the next batch. Identifiers are grouped by consecutive numeric value while retaining their original spelling. The first range at or beyond the threshold belongs at the start of the final batch.",
    [{"items": [str(i + x).zfill(3) for x in [1, 2, 4, 5, 8, 9]], "threshold": i + 4} for i in range(30)],
)
workflow(
    "Committed journal page construction",
    "more_itertools",
    "split_after chunked",
    "segments = m.split_after(data['items'], lambda item:item=='commit', maxsplit=1)\nresult = [list(m.chunked(segment, data['size'], strict=True)) for segment in segments]",
    "Committed journal pages repeat a commit token and occasionally accept an incomplete page. The commit token closes the first segment and appears only there. Each segment is divided into complete pages; an incomplete segment must be rejected instead of silently producing a short page.",
    [
        {"items": ["entry" + str(i), "commit"] + [str(x) for x in range(4 + (i % 2))], "size": 2}
        for i in range(30)
    ],
)
workflow(
    "Minimum-capacity balanced block assignment",
    "more_itertools",
    "padded divide",
    "items = list(m.padded(data['items'], 0, data['minimum']))\nblocks = m.divide(data['parts'], items)\nresult = [None]*data['parts']\nfor index in data['order']:\n    result[index] = list(blocks[index])",
    "Balanced block assignments truncate input above minimum capacity and depend on block read order. Capacity is a lower bound: retain all source items and add zeros only if needed. Blocks remain contiguous, differ in length by at most one, and retain their assigned contents regardless of consumption order.",
    [
        {
            "items": list(range(i, i + 7)),
            "minimum": 3 + i % 7,
            "parts": 3,
            "order": [2, 0, 1] if i % 2 else [1, 2, 0],
        }
        for i in range(30)
    ],
)
workflow(
    "Ordered channel validation",
    "more_itertools",
    "distribute is_sorted",
    "streams = m.distribute(data['channels'], iter(data['items']))\nresult = [None]*data['channels']\nfor index in data['order']:\n    values = list(streams[index])\n    result[index] = {'items': values, 'ordered': m.is_sorted(values, reverse=True, strict=data['strict'])}",
    "Channel validation reports the wrong data and ordering status when readers run in a different order. Each round-robin channel has stable ownership of its source positions. Its descending-order flag must reflect that channel’s values, including the configured policy on ties.",
    [
        {
            "items": [
                [20 + i - x for x in range(9)],
                [20 + i - (x // 4) for x in range(9)],
                [i + x for x in range(9)],
                [20 + i - x if x != 6 else 99 for x in range(9)],
            ][i % 4],
            "channels": 3,
            "order": [2, 0, 1],
            "strict": bool((i // 4) % 2),
        }
        for i in range(30)
    ],
)
workflow(
    "Balanced block window export",
    "more_itertools",
    "divide windowed",
    "blocks = m.divide(data['parts'], data['items'])\nresult = [None]*data['parts']\nfor index in data['order']:\n    result[index] = list(m.windowed(blocks[index], data['width'], step=data['step'], fillvalue=0))",
    "Block-window exports assign records to the wrong block and produce malformed final windows. Balanced contiguous blocks must be independent readers. Windows belong to each block’s own records and retain the required padding without adding source-free windows.",
    [
        {
            "items": list(range(i, i + 8 + (i % 3))),
            "parts": 3,
            "order": [2, 0, 1],
            "width": 3 + i % 2,
            "step": 4 + i % 2,
        }
        for i in range(30)
    ],
)
workflow(
    "Scalar-or-list field redaction",
    "more_itertools",
    "always_iterable replace",
    "fields = m.always_iterable(data['fields'])\nresult = list(m.replace(fields, lambda field:field==data['target'], ['redacted'], count=data['limit']))",
    "Field redaction behaves differently for one text field and a list of fields, loses neighboring fields, and exceeds the replacement limit. Text is one field unless explicitly supplied as a list. Replacements preserve all nonmatching fields and stop at the requested count.",
    [
        {
            "fields": ("secret" + str(i))
            if i % 3 == 0
            else ["secret" + str(i), "visible", "secret" + str(i), "tail"],
            "target": "secret" + str(i),
            "limit": i % 3,
        }
        for i in range(30)
    ],
)
workflow(
    "Range batches with a closing range",
    "more_itertools",
    "consecutive_groups split_after",
    "ranges = [list(group) for group in m.consecutive_groups(data['items'], ordering=int)]\nresult = list(m.split_after(ranges, lambda group:len(group)>=data['length'], maxsplit=1))",
    "Range batches lose grouping and repeat their closing range in the following batch. Numeric adjacency determines each range, preserving original labels. The first range meeting the size threshold closes its batch and must not appear again in the remainder.",
    [{"items": [str(i + x).zfill(3) for x in [1, 2, 3, 6, 7, 10]], "length": 3} for i in range(30)],
)
workflow(
    "Change-series ordering audit",
    "more_itertools",
    "difference is_sorted",
    "changes = list(m.difference(data['items']))\nresult = {'changes': changes, 'ordered': m.is_sorted(changes, reverse=True, strict=data['strict'])}",
    "Change-series audits disagree with the original readings and their ordering verdict. The first reading is retained, later values measure current minus previous, and the audit checks whether those changes are descending under the configured tie policy. Values and verdict must describe the same series.",
    [
        {
            "items": [
                [10 + i, 17 + i, 22 + i, 25 + i],
                [10 + i, 20 + 2 * i, 30 + 3 * i, 40 + 4 * i],
                [1 + i, 3 + 3 * i, 7 + 7 * i, 15 + 15 * i],
                [20 + i, 23 + i, 29 + i, 30 + i],
            ][i % 4],
            "strict": bool((i // 4) % 2),
        }
        for i in range(30)
    ],
)
workflow(
    "Redacted token window transport",
    "more_itertools",
    "replace windowed",
    "tokens = m.replace(data['items'], lambda a,b:a=='private' and b=='value', ['redacted'], count=data['limit'], window_size=2)\nresult = list(m.windowed(tokens, data['width'], step=data['step'], fillvalue='pad'))",
    "Token transport drops content after a redacted pair and emits malformed windows at stream boundaries. Redaction replaces non-overlapping private/value pairs up to the configured limit. Windows then cover the resulting stream, preserving remaining tokens and only the required final padding.",
    [
        {
            "items": ["start", "private", "value", "middle", "private", "value", "end"][: 3 + i % 5],
            "limit": i % 3,
            "width": 3 + i % 2,
            "step": 4 + i % 2,
        }
        for i in range(30)
    ],
)
workflow(
    "Balanced ordered partition audit",
    "more_itertools",
    "is_sorted divide",
    "blocks = m.divide(data['parts'], data['items'])\nresult = [None]*data['parts']\nfor index in data['order']:\n    values = list(blocks[index])\n    result[index] = {'items': values, 'ordered': m.is_sorted(values, reverse=True, strict=data['strict'])}",
    "Partition audits depend on reader order and reject correctly descending blocks. Each balanced contiguous partition must retain its assigned values independently. Ordering checks apply to those values with the configured tie policy, rather than changing the allocation or reversing the contract.",
    [
        {
            "items": [
                [30 + i - x for x in range(8 + i % 3)],
                [30 + i - x // 2 for x in range(8 + i % 3)],
                [i + x for x in range(8 + i % 3)],
                [30 + i - x if x != 2 else 99 for x in range(8 + i % 3)],
            ][i % 4],
            "parts": 3,
            "order": [2, 0, 1],
            "strict": bool((i // 4) % 2),
        }
        for i in range(30)
    ],
)
workflow(
    "Feature-pair enumeration from scalar or list input",
    "more_itertools",
    "distinct_combinations always_iterable",
    "features = m.always_iterable(data['features'])\nresult = list(m.distinct_combinations(features, data['size']))",
    "Feature-pair exports split single text labels into characters and reuse feature positions. A scalar text label is one feature; an explicit list contains its listed features. Combinations preserve input order and may use duplicate values only when distinct input positions supply them.",
    [
        {
            "features": ("AB" + str(i))
            if i % 2 == 0
            else ["A" + str(i), "A" + str(i), "B" + str(i), "C" + str(i)],
            "size": 2 + (i % 2),
        }
        for i in range(30)
    ],
)

DEFECTS = {index: defect[0] for index, defect in OLD_DEFECTS.items()}
# Every task occurs twice across the four accounts; all queues have14+6 composition.
solvable = [f"C{i:03d}" for i in range(1, 41) if i not in DEFECTS]
broken = [f"C{i:03d}" for i in DEFECTS]
ASSIGNMENTS = {}
for account in range(4):
    good = [solvable[(account * 7 + i) % 28] for i in range(14)]
    bad = [broken[(account * 3 + i) % 12] for i in range(6)]
    queue = []
    for index in range(20):
        if (
            index
            in [{2, 5, 8, 12, 16, 19}, {3, 6, 10, 13, 15, 18}, {2, 7, 9, 12, 15, 18}, {4, 6, 9, 11, 16, 19}][
                account
            ]
        ):
            queue.append(bad.pop(0))
        else:
            queue.append(good.pop(0))
    ASSIGNMENTS[str(2001 + account)] = queue
