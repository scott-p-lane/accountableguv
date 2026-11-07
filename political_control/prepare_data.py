"""Prepare political reference data from cached official source pages."""
from html.parser import HTMLParser
from pathlib import Path
import calendar
import datetime as dt
import json
import re

ROOT = Path(__file__).resolve().parent
AS_OF = dt.date(2026, 11, 6)
START = dt.date(1977, 1, 1)
END = dt.date(2026, 10, 31)  # completed calendar months only


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = None
        self.cell = None
        self.in_sup = False

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.cells = []
        elif tag in ('td', 'th') and self.cells is not None:
            self.cell = []
        elif tag == 'sup':
            self.in_sup = True
        elif tag == 'br' and self.cell is not None:
            self.cell.append(' | ')

    def handle_endtag(self, tag):
        if tag == 'sup':
            self.in_sup = False
        elif tag in ('td', 'th') and self.cell is not None:
            self.cells.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.cells is not None:
            self.rows.append(self.cells)
            self.cells = None

    def handle_data(self, data):
        if self.cell is not None and not self.in_sup:
            self.cell.append(data)


def date(text):
    return dt.datetime.strptime(text, '%m/%d/%Y').date()


def senate_events():
    parser = Rows()
    parser.feed((ROOT / 'source/senate.html').read_text(encoding='utf-8'))
    congress = None
    session_start = None
    parties = None
    events = []
    for row in parser.rows:
        title = re.search(r'(\d+)\w* Congress\s*\((\d+/\d+/\d+) to (\d+/\d+/\d+)\)', ' '.join(row))
        if title:
            congress = int(title[1])
            congress_start = date(title[2])
            first = True
        if congress is None or congress < 94:
            continue
        if len(row) == 6 and 'session' in row[0] and row[1] in ('Democrats', 'Republicans'):
            parties = row[1:3]
            m = re.search(r'\((\d+/\d+/\d+)\s*[-–]', row[0])
            session_start = date(m[1]) if m else None
        if len(row) != 6 or not row[1].isdigit() or not row[2].isdigit() or not row[4].isdigit() or not row[5].isdigit():
            continue
        if parties is None:
            continue
        if row[0]:
            m = re.match(r'(\d+/\d+/\d+)', row[0])
            if not m:
                raise ValueError(('Unrecognized event date', congress, row))
            effective = date(m[1])
        else:
            effective = congress_start if first else session_start
        if effective is None:
            raise ValueError(('Missing session start', congress, row))
        # First session may convene after Jan 3. Source describes the opening
        # composition; use term start for otherwise undated opening counts.
        counts = {'Democrat': 0, 'Republican': 0, 'Independent': 0, 'Independent Democrat': 0}
        for party, value in zip(parties, row[1:3]):
            counts['Democrat' if party == 'Democrats' else 'Republican'] = int(value)
        if row[3] != '0':
            found = re.findall(r'(\d+)\s+(Independent Democrat|Independents?|Conservative)', row[3])
            if row[3].isdigit() and congress == 107:
                found = [(row[3], 'Independent')]  # Jeffords/Barkley, named in source footnotes
            if not found:
                raise ValueError(('Unknown other party', congress, row))
            for value, party in found:
                party = 'Independent' if party == 'Independents' else party
                counts[party] = counts.get(party, 0) + int(value)
        assert sum(counts.values()) + int(row[4]) == int(row[5]) == 100, row
        events.append({'date': str(effective), 'congress': congress, **counts,
                       'controlling_party': 'Democrat' if parties[0] == 'Democrats' else 'Republican',
                       'vacant': int(row[4]), 'source_row': row})
        first = False
    # Retain the latest row where source repeats a date.
    unique = {e['date']: e for e in events}
    return sorted(unique.values(), key=lambda e: e['date'])


HOUSE_URL = 'https://history.house.gov/Institution/Party-Divisions/Party-Divisions/'
SENATE_URL = 'https://www.senate.gov/about/parties-leadership/party-division.shtml'
PRESIDENT_URL = 'https://history.house.gov/Institution/Presidents-Coinciding/Presidents-Coinciding/'
PARTY_URL = 'https://history.house.gov/Institution/Presidents-Coinciding/Party-Government/'


def house_events():
    parser = Rows()
    parser.feed((ROOT / 'source/house.html').read_text(encoding='utf-8'))
    events = []
    for row in parser.rows:
        match = re.match(r'(\d+)\w* \((\d{4})', row[0]) if row else None
        if not match or not 94 <= int(match[1]) <= 119:
            continue
        other = int(re.search(r'\((\d+)\)', row[4])[1]) if row[4] != '0' else 0
        assert row[4] == '0' or row[4].startswith('Independent'), row
        total, dem, rep = map(int, row[1:4])
        events.append({'date': f'{match[2]}-01-03', 'congress': int(match[1]),
                       'democrat_seats': dem, 'republican_seats': rep,
                       'independent_seats': other, 'other_seats': 0,
                       'unassigned_seats': total-dem-rep-other,
                       'total_seats': total})
    assert len(events) == 26
    return events


def months():
    for year in range(START.year, END.year + 1):
        for month in range(1, 13):
            end = dt.date(year, month, calendar.monthrange(year, month)[1])
            if end > END:
                return
            yield {'year': year, 'month': month, 'year_month': f'{year}-{month:02}',
                   'month_start': f'{year}-{month:02}-01', 'month_end': str(end),
                   'fiscal_year': year + (month >= 10),
                   'fiscal_month': (month + 2) % 12 + 1}


def latest(events, day):
    return max((e for e in events if e['date'] <= day), key=lambda e: e['date'])


def datasets():
    terms = [
        (38, 'Gerald Ford', 'Republican', '1974-08-09', '1977-01-20'),
        (39, 'Jimmy Carter', 'Democrat', '1977-01-20', '1981-01-20'),
        (40, 'Ronald Reagan', 'Republican', '1981-01-20', '1989-01-20'),
        (41, 'George H. W. Bush', 'Republican', '1989-01-20', '1993-01-20'),
        (42, 'Bill Clinton', 'Democrat', '1993-01-20', '2001-01-20'),
        (43, 'George W. Bush', 'Republican', '2001-01-20', '2009-01-20'),
        (44, 'Barack Obama', 'Democrat', '2009-01-20', '2017-01-20'),
        (45, 'Donald Trump', 'Republican', '2017-01-20', '2021-01-20'),
        (46, 'Joe Biden', 'Democrat', '2021-01-20', '2025-01-20'),
        (47, 'Donald Trump', 'Republican', '2025-01-20', ''),
    ]
    presidents = [dict(zip(['presidency_number', 'president', 'party', 'office_start_date', 'office_end_date'], t),
                       source_url=PRESIDENT_URL, party_source_url=PARTY_URL, retrieved_on=str(AS_OF)) for t in terms]
    def president_on(day):
        return next(p for p in presidents if p['office_start_date'] <= day and
                    (not p['office_end_date'] or day < p['office_end_date']))
    monthly_presidents, monthly_house, monthly_senate = [], [], []
    house, senate = house_events(), senate_events()
    # Senate party-switch history supplies Smith's temporary independent status,
    # which is not shown in the main division table's current 106th-Congress rows.
    switch_url = 'https://www.senate.gov/senators/SenatorsWhoChangedPartiesDuringSenateService.htm'
    for day, rep, independent in [('1999-07-13', 54, 1), ('1999-11-01', 55, 0)]:
        original = latest(senate, day)
        senate.append({**original, 'date': day, 'Republican': rep, 'Independent': independent,
                       'supplement_source_url': switch_url})
    senate.sort(key=lambda e: e['date'])
    for period in months():
        begin, end = period['month_start'], period['month_end']
        first_pres, last_pres = president_on(begin), president_on(end)
        monthly_presidents.append({**period, **last_pres,
            'president_at_month_start': first_pres['president'],
            'party_at_month_start': first_pres['party'],
            'president_changed_in_month': int(first_pres['presidency_number'] != last_pres['presidency_number']),
            'party_changed_in_month': int(first_pres['party'] != last_pres['party']),
            'observation_basis': 'month_end'})
        h = latest(house, end)
        monthly_house.append({**period, 'congress': h['congress'],
            **{k: v for k, v in h.items() if k.endswith('_seats')},
            'controlling_party': 'Democrat' if h['democrat_seats'] > h['republican_seats'] else 'Republican',
            'baseline_effective_date': h['date'],
            'congress_changed_in_month': int(latest(house, begin)['congress'] != h['congress']),
            'observation_basis': 'congress_initial_election_result_baseline',
            'source_url': HOUSE_URL, 'retrieved_on': str(AS_OF)})
        s = latest(senate, end)
        start_s = latest(senate, begin)
        # Ignore repeated annual source observations when detecting changes.
        fields = ['Democrat', 'Republican', 'Independent', 'Independent Democrat', 'vacant', 'controlling_party']
        state = tuple(start_s[k] for k in fields)
        changed = False
        for event in sorted((e for e in senate if begin < e['date'] <= end), key=lambda e: e['date']):
            next_state = tuple(event[k] for k in fields)
            changed |= next_state != state
            state = next_state
        monthly_senate.append({**period, 'congress': s['congress'],
            'democrat_seats': s['Democrat'], 'republican_seats': s['Republican'],
            'independent_seats': s['Independent'], 'independent_democrat_seats': s['Independent Democrat'],
            'other_seats': s.get('Conservative', 0), 'vacant_seats': s['vacant'], 'total_seats': 100,
            'controlling_party': s['controlling_party'],
            'controlling_party_at_month_start': start_s['controlling_party'],
            'reported_composition_changed_in_month': int(changed),
            'source_observation_date': s['date'],
            'observation_basis': 'latest_official_reported_composition_at_month_end',
            'source_url': SENATE_URL, 'supplement_source_url': s.get('supplement_source_url', ''),
            'retrieved_on': str(AS_OF)})
    for rows in [monthly_presidents, monthly_house, monthly_senate]:
        assert len(rows) == 598
        assert len({r['year_month'] for r in rows}) == len(rows)
    for row in monthly_house:
        assert sum(row[k] for k in ['democrat_seats', 'republican_seats', 'independent_seats', 'other_seats', 'unassigned_seats']) == 435
    for row in monthly_senate:
        assert sum(row[k] for k in ['democrat_seats', 'republican_seats', 'independent_seats', 'independent_democrat_seats', 'other_seats', 'vacant_seats']) == 100
    house_by_month = {row['year_month']: row for row in monthly_house}
    senate_by_month = {row['year_month']: row for row in monthly_senate}
    president_months = {row['year_month'] for row in monthly_presidents}
    assert president_months == set(house_by_month) == set(senate_by_month)
    combined = []
    for president in monthly_presidents:
        key = president['year_month']
        row = {
            'year': president['year'],
            'month': president['month'],
            'president_name': president['president'],
            'president_party': president['party'],
            'house_majority_party': house_by_month[key]['controlling_party'],
            'senate_majority_party': senate_by_month[key]['controlling_party'],
        }
        assert all(row[field] in {'Republican', 'Democrat'} for field in
                   ('president_party', 'house_majority_party', 'senate_majority_party'))
        combined.append(row)
    return {'presidents.csv': presidents, 'presidents_monthly.csv': monthly_presidents,
            'house_party_counts_monthly.csv': monthly_house, 'senate_party_counts_monthly.csv': monthly_senate,
            'political_control_monthly.csv': combined}


if __name__ == '__main__':
    data = datasets()
    (ROOT / 'source/datasets.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    print({name: len(rows) for name, rows in data.items()})
