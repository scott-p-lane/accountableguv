"""Convert Treasury STAR fixed-width archive reports to monthly MTS payloads."""

from collections import Counter, defaultdict
from calendar import month_abbr, month_name
import re


TABLE_TITLE = re.compile(r"^\s+TABLE ([1-9])([A-Z]?)\.\s+(.+)", re.I)
RULE = re.compile(r"^\+\s+_{20,}(?:\s+_{8,})+\s*$")
AMOUNT = re.compile(r"[+-]?\s*(?:\d{1,3}(?:[, .]\d{3})+|\d+)")
FORMAT_CODE = re.compile(r";[A-Z](?=[A-Z(])")
AMOUNT_SEPARATORS = str.maketrans("", "", ", .")
FIELD = re.compile(r"\S(?:[^\t\r\n]*?\S)?(?= {2,}|\t|\s*$)")
NOTES = re.compile(
    r"^\s*(?:[0-9-]?REPORT ID:|USER ID\s*:|DATE:|FOOTNOTES?:|\d+/\s{2,}[A-Za-z]|"
    r"Note:\s+Details|STAR - TREASURY FINANCIAL DATABASE|Daily Treasury Statement \(Available|"
    r"PAGE\s+\d+\(\d+\)\s*$)", re.I,
)
MONTHS = {name.upper(): f"{short.lower()}_rcpt_outly_amt"
          for name, short in zip(month_name[1:], month_abbr[1:])}
FISCAL_MONTH_NUMBERS = {name.upper(): index for index, name in enumerate(
    month_name[10:] + month_name[1:10], start=1)}
FINANCING = "current_month_net_txn_amt fytd_net_txn_amt prior_fytd_net_txn_amt"
BALANCES = "begin_year_acct_bal_amt begin_month_acct_bal_amt close_month_acct_bal_amt"
RECEIPTS_OUTLAYS = "current_month_rcpt_outly_amt current_fytd_rcpt_outly_amt prior_fytd_rcpt_outly_amt"


def amount(token, line_number):
    if not token or re.fullmatch(r"\.+|\(\*+\)|\*+|[-+]", token):
        return None
    token = re.sub(r"^\d+/\s*", "", token)
    if not AMOUNT.fullmatch(token):
        raise ValueError(f"Unrecognized amount {token!r} on source line {line_number}")
    # STAR prints whole millions, while the Fiscal Data API reports dollars.
    return str(int(token.translate(AMOUNT_SEPARATORS)) * 1_000_000)


def read_row(line, runs, line_number, fields):
    label_start = runs[0].start()
    ends = [run.end() for run in runs]
    label = line[label_start:ends[0]].rstrip()
    tokens = [line[start:end].strip() for start, end in zip(ends, [*ends[1:-1], len(line)])]
    tabbed_total = re.fullmatch(
        r"(\s+;[BC]TOTAL (?:SURPLUS \(\+\) OR DEFICIT|ON-BUDGET|OFF-BUDGET))[ \t]+([+-]?[\d,]+)\s*",
        line,
    )
    if "\t" in line and fields[-1].endswith("_net_outly_amt") and tabbed_total:
        # Table 5 prints only net amounts on these final surplus/deficit rows.
        tokens = ["", "", tabbed_total[2]]
        return tabbed_total[1][label_start:], tokens, [None, None, amount(tokens[-1], line_number)]
    if (fields[0] == "current_month_net_txn_amt" and
            label.strip() == "REVISIONS BY FEDERAL AGENCIES TO THE PRIOR BUDGET RESULTS" and
            tokens == ["....22", "416", "2,924"]):
        # July 2005 Schedule A prints 22 over a placeholder. The before/after
        # balances are 4,366,902 and 4,366,924 million.
        tokens[0] = "22"
    if (fields[0] == "current_month_gross_outly_amt" and label.strip() == ";CTOTAL--DEPARTMENT OF EDUCATION"
            and tokens == ["-,551", "9", "-,560"]):
        # August 2001 Table 3 also reports net Education outlays of -560.
        tokens = ["-551", "9", "-560"]
    try:
        if any(line[end - 1:end].strip() and line[end:end + 1].strip() for end in ends[:-1]):
            raise ValueError("Text straddles a column boundary")
        return label, tokens, [amount(token, line_number) for token in tokens]
    except ValueError as original_error:
        # Some archived reports contain manually edited spacing. Use all columns
        # in order only when their tokens are individually valid and unambiguous.
        parts = list(FIELD.finditer(line))
        if len(parts) != len(ends) or parts[1].start() < ends[0] - 4:
            raise ValueError(f"Unrecognized row alignment on source line {line_number}") from original_error
        label = line[label_start:parts[0].end()].rstrip()
        tokens = [part[0] for part in parts[1:]]
        return label, tokens, [amount(token, line_number) for token in tokens]


def amount_fields(table, heading, columns, title):
    if table == 1:
        return "current_month_gross_rcpt_amt current_month_gross_outly_amt current_month_dfct_sur_amt".split()
    if table == 2:
        return ("prior_fytd_budget_amt next_year_budget_est_amt" if "NEXT FY" in heading else
                "current_month_budget_amt current_fytd_budget_amt current_year_budget_est_amt").split()
    if table == 3:
        return (RECEIPTS_OUTLAYS + " current_year_budget_est_amt").split()
    if table == 5 and title.startswith("(MEMORANDUM)"):
        return ["current_fytd_app_rcpt_amt", "prior_fytd_app_rcpt_amt"]
    if table in (4, 5):
        period = next((key for text, key in (("THIS MONTH", "current_month"),
                                           ("CURRENT FYTD", "current_fytd"),
                                           ("PRIOR FYTD", "prior_fytd")) if text in heading), None)
        if period:
            kinds = ("gross_rcpt refund net_rcpt" if table == 4 else "gross_outly app_rcpt net_outly")
            return [f"{period}_{kind}_amt" for kind in kinds.split()]
    if table in (6, 8) and "CLOSE OF THIS MONTH" in heading:
        return BALANCES.split()
    if table == 6:
        return FINANCING.split()
    if table == 7:
        if all(column in MONTHS for column in columns):
            return [MONTHS[column] for column in columns]
        if "PRIOR" in heading and len(columns) == 2:
            return ["current_fytd_rcpt_outly_amt", "prior_fytd_rcpt_outly_amt"]
    if table == 8:
        period = "current_month" if "CURRENT MONTH" in heading else "fytd" if "FYTD" in heading else None
        if period:
            return [f"{period}_{kind}_amt" for kind in ("rcpt", "outly", "excess")]
    if table == 9:
        return RECEIPTS_OUTLAYS.split()
    raise ValueError(f"Unrecognized Table {table} columns: {heading.strip()}")


def restore_december_1999_lines(lines):
    """Unwrap the December 1999 text file while retaining source line numbers."""
    for index in range(len(lines) - 1):
        line, continuation = lines[index:index + 2]
        if len(line) < 100 or not continuation.strip() or len(continuation) > 40:
            continue
        if (re.fullmatch(r"[\d ,.+*/()_-]+", continuation) or
                re.search(r"TABLE [1-9]|CLASSIFICATION|\bPERIOD\b|\bFYTD\b|BUDGET EST\.|ACTUAL|BALANCES", line)):
            separator = "" if line.endswith(" ") or continuation.startswith(" ") else " "
            lines[index] = line + separator + continuation
            lines[index + 1] = ""


def report_sections(body, report_date):
    lines = body.decode("cp1252", errors="replace").splitlines()
    if report_date.isoformat() == "1999-12-31":
        restore_december_1999_lines(lines)
    sections = defaultdict(list)
    title = None
    active = False
    for index, line in enumerate(lines):
        title_match = TABLE_TITLE.match(line)
        if title_match:
            table, suffix, title = int(title_match[1]), title_match[2], title_match[3]
            active = False
        elif line.startswith("1 ") or NOTES.match(line):
            active = False
        elif RULE.fullmatch(line):
            if title is None:
                raise ValueError(f"Column rule before any table title on source line {index + 1}")
            header = [value for value in lines[max(0, index - 14):index] if value.strip()]
            if not re.search(rf"ACCOUNTING DATE:\s+{report_date:%m/%y}\b", "\n".join(header)):
                raise ValueError(f"Unexpected or missing accounting date before source line {index + 1}")
            units = " ".join(lines[max(0, index - 10):index])
            if not re.search(r"\(IN\s+MILLIONS\)", units):
                raise ValueError(f"Unverified units for Table {table}: {title}")
            runs = list(re.finditer("_+", line))
            # Field widths extend from the end of the previous underline to the next.
            ends = [run.end() for run in runs]
            header_lines = header[-2:]
            columns = [header_lines[-1][start:end].strip() for start, end in zip(ends, ends[1:])]
            heading = " ".join(header_lines)
            try:
                fields = tuple(amount_fields(table, heading, columns, title))
            except ValueError as error:
                raise ValueError(f"{error} on source line {index + 1} ({title})") from error
            if len(fields) != len(columns):
                raise ValueError(f"Unexpected number of columns on source line {index + 1}")
            # A table can have independent schedules as well as repeated groups of columns.
            group = suffix or (title.split(" - ", 1)[0]
                               if title.startswith(("SCHEDULE", "(MEMORANDUM)")) else "")
            current = sections[table]
            if not current or current[-1][:2] != (group, fields):
                current.append((group, fields, []))
            active = True
        elif active and line.startswith(" ") and line.strip():
            if (table == 3 and report_date.isoformat() == "2000-10-31"
                    and line.strip() == ";CRESERVE FOR AMERICA'S FUTURE (ON-BUDGET)"
                    and not line[:ends[0]].strip()
                    and lines[index + 1].split() == ["......", "......", "......", "20,000"]):
                # This row was displaced over two lines in the archived text.
                tokens = lines[index + 1].split()
                current[-1][2].append((";CRESERVE FOR AMERICA'S FUTURE (ON-BUDGET)", tokens,
                                       [amount(token, index + 2) for token in tokens], index + 1))
                continue
            label, tokens, values = read_row(line, runs, index + 1, fields)
            if not label.strip() and any(tokens):
                raise ValueError(f"Unrecognized row alignment on source line {index + 1}")
            if label.strip():
                current[-1][2].append((label, tokens, values, index + 1))
    return sections


def merge_rows(sections, report_date, table, schema):
    groups = {}
    seen_fields = set()
    for group, fields, lines in sections:
        seen_fields.update(fields)
        if not lines:
            raise ValueError(f"No rows found for Table {table} {group} ({', '.join(fields)})")
        occurrences = Counter()
        records = groups.setdefault(group, {})
        for label, tokens, values, source_line in lines:
            indent = len(label) - len(label.lstrip())
            name = FORMAT_CODE.sub("", label.strip())
            key = (indent, name)
            occurrences[key] += 1
            key = (*key, occurrences[key])
            record = records.setdefault(key, (source_line, set(), {}))
            if set(fields) & record[2].keys():
                raise ValueError(f"Repeated columns for Table {table} on source line {source_line}")
            record[1].update(token for token in tokens if token)
            record[2].update(zip(fields, values))
    missing_fields = {key for key, kind in schema.items() if kind == "CURRENCY"} - seen_fields
    if missing_fields:
        raise ValueError(f"Table {table} is missing columns: {', '.join(sorted(missing_fields))}")

    fiscal_month = (report_date.month + 2) % 12 + 1
    base_row = dict.fromkeys(schema)
    fiscal_year = report_date.year + (report_date.month >= 10)
    base_row.update(
        record_date=str(report_date), table_nbr=str(table),
        record_fiscal_year=str(fiscal_year),
        record_fiscal_quarter=str((fiscal_month - 1) // 3 + 1),
        record_calendar_year=f"{report_date.year:04}", record_calendar_month=f"{report_date.month:02}",
        record_calendar_day=f"{report_date.day:02}", record_calendar_quarter=str((report_date.month - 1) // 3 + 1),
    )
    rows = []
    for group, records in groups.items():
        for (_, label, _), (source_line, tokens, values) in records.items():
            description = display_label(table, label, fiscal_year)
            rows.append(dict(base_row, **values, classification_desc=description,
                             src_line_nbr=str(source_line), print_order_nbr=str(len(rows) + 1),
                             data_type_cd=("T" if label.startswith("TOTAL") else "D") if tokens else "S",
                             classification_id=f"archive:{report_date}:{table}:{source_line}"))
    if not any(any(row[key] is not None for key in seen_fields) for row in rows):
        raise ValueError(f"Table {table} contains no published amounts")
    if table == 1:
        assign_table_1_sequences(rows, fiscal_year, fiscal_month)
    return rows


def assign_table_1_sequences(rows, fiscal_year, fiscal_month):
    headings = {f"FY {fiscal_year - 1}": "1", f"FY {fiscal_year}": "2"}
    fiscal_group = None
    for row in rows:
        label = row["classification_desc"].upper()
        if label in headings:
            fiscal_group = headings[label]
            row.update(sequence_level_nbr="1", sequence_number_cd=fiscal_group)
            continue
        position = FISCAL_MONTH_NUMBERS.get(label)
        if label == "YEAR-TO-DATE":
            position = 13 if fiscal_group == "1" else fiscal_month + 1
        if fiscal_group is None or position is None:
            raise ValueError(f"Unexpected Table 1 row on source line {row['src_line_nbr']}: {label}")
        row.update(sequence_level_nbr="2", sequence_number_cd=f"{fiscal_group}.{position}")


def display_label(table, label, fiscal_year):
    if table == 1 and label in ("PRIOR YEAR", "CURRENT YEAR"):
        return f"FY {fiscal_year - (label == 'PRIOR YEAR')}"
    if table == 1 and label in MONTHS:
        return label.title()
    if table == 4:
        label = re.sub(r"^TOTAL\s*--\s*", "TOTAL -- ", label)
        label = label.replace("SOCIAL INSURANCE TAXES AND CONTRIBUTIONS",
                              "SOCIAL INSURANCE AND RETIREMENT RECEIPTS") if label.startswith("TOTAL") else label
    # The existing workbooks filter by the modern spelling of these archive labels.
    if table in (4, 6):
        workbook_labels = {
            "Corporation Income Taxes", "Customs Duties", "Estate and Gift Taxes",
            "Total -- Excise Taxes", "Total -- Individual Income Taxes",
            "Total -- Miscellaneous Receipts", "Total -- Social Insurance and Retirement Receipts",
            "Debt Held by the Public", "Intragovernmental Holdings",
        }
        return next((name for name in workbook_labels if name.upper() == label), label)
    return label


def transform_report(body, report_date, source_url, source_types):
    sections = report_sections(body, report_date)
    if sections.keys() != set(range(1, 10)):
        raise ValueError("Archive report must contain all nine MTS tables")
    tables = {}
    for number, parts in sections.items():
        table = f"mts_table_{number}"
        schema = source_types(table)
        rows = merge_rows(parts, report_date, number, schema)
        tables[table] = {
            "report_date": str(report_date), "source_url": source_url, "data": rows,
            "meta": {"dataTypes": schema, "count": len(rows),
                     "archive": {"format": "treasury-star-text", "published_amount_unit": "millions"}},
        }
    return tables
