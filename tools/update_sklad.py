"""Еженедельная актуализация страницы sklad-pivo/index.html.

Запуск из корня репозитория:
    python tools/update_sklad.py sklad-pivo/updates/2026-11-16.json

Скрипт читает данные, зашитые в страницу (<script id="data">), применяет файл
обновления (результаты проверки объявлений и новые объявления), пересчитывает
вердикты, места и таблицу отсева и записывает страницу обратно. Повторный запуск
с тем же файлом ничего не ломает. Формат файла обновления — в tools/README.md.
"""
import collections
import datetime as dt
import json
import re
import sys

HTML = 'sklad-pivo/index.html'
COLLECTED = dt.date(2026, 10, 28)          # дата исходного сбора: к ней привязаны «сегодня», «вчера»
MON = {'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'мая': 5, 'май': 5, 'июн': 6, 'июл': 7,
       'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12}
STALE = 'объявление старше 3 месяцев'
GONE = 'объявление снято'
ORDER = {'финал': 0, 'запас': 1, 'отсев': 2}


def sp(n):
    return f'{int(round(n)):,}'.replace(',', ' ')


def ru(d):
    return f'{d[8:10]}.{d[5:7]}.{d[:4]}'


def comma(v):
    return str(v).replace('.', ',')


def date_iso(s):
    """Дата объявления в ISO или None (Авито без даты, каталоги с номером вместо даты)."""
    s = (s or '').strip()
    if re.fullmatch(r'\d{4}-\d\d-\d\d', s):
        return s
    if s.startswith('сегодня'):
        return COLLECTED.isoformat()
    if s.startswith('вчера'):
        return (COLLECTED - dt.timedelta(days=1)).isoformat()
    m = re.match(r'(\d{1,2}) ([а-я]{3})', s)
    if m and m.group(2) in MON:
        return f'{COLLECTED.year}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}'
    return None


def minus_3_months(d):
    y, m = d.year, d.month - 3
    if m < 1:
        y, m = y - 1, m + 12
    day = min(d.day, [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day)


def price_part(x, med):
    if not x.get('m2'):
        return ['Цена', 'не указана', 0]
    r = x['m2'] / med
    pts = max(0, min(20, round(12 - 40 * (r - 1))))
    sign = '+' if r >= 1 else '−'
    return ['Цена', f"{sp(x['m2'])} ₽/м² в мес — {sign}{abs(round((r - 1) * 100))} % к середине отобранных ({sp(med)} ₽)", pts]


def rescore(x, med):
    x['parts'] = [price_part(x, med) if p[0] == 'Цена' else p for p in x['parts']]
    x['score'] = sum(p[2] for p in x['parts'])


def new_item(n, D):
    """Карточка нового объявления из файла обновления. Правила те же, что при уточнении 29.10.2026."""
    h, area = n.get('h'), n.get('area')
    sklad = n.get('sklad_area') or area
    x = {
        'key': n['key'], 'src': n['src'], 'url': n['url'], 'place': n['place'], 'kind': n.get('kind', 'склад'),
        'area': area, 'rub': n.get('rub'), 'vat': n.get('vat', ''), 'h': h, 'h_cit': n.get('h_cit', ''),
        'teplo': n.get('teplo', ''), 'teplo_cit': '', 'doki': n.get('doki'), 'klass': n.get('klass', ''),
        'nagr': n.get('nagr'), 'bespyl': bool(n.get('bespyl')), 'stell': bool(n.get('stell')), 'stell_cit': '',
        'zhd': n.get('zhd', 'N'), 'zhd_weak': bool(n.get('zhd_weak')), 'zhd_cit': n.get('zhd_cit', ''), 'zhd_bad': '',
        'zhd_t': {'A': 'рампа у ветки', 'B': 'ветка на территории', 'N': 'не указана'}[n.get('zhd', 'N')],
        'vetka': n.get('vetka'), 'vetka_osm': 'rail', 'kmb': 0 if n.get('city', True) else n.get('kmb'),
        'kmb_how': 'в границах Новосибирска' if n.get('city', True) else n.get('kmb_how', ''),
        'city': bool(n.get('city', True)), 'lat': n.get('lat'), 'lon': n.get('lon'), 'geo': n.get('geo', 'точка из объявления'),
        'approx': False, 'photos': [], 'text': n.get('text', ''), 'date': n.get('date', ''), 'seller': n.get('seller', ''),
        'dubli': n.get('dubli', []), 'sosedi': [], 'rayon': n.get('rayon', ''), 'pet': 'петухова' in n['place'].lower(),
        'added': n.get('added'), 'manual_note': n.get('note', ''), 'upd': n.get('upd'),
    }
    x['m2'] = round(x['rub'] / area) if x['rub'] and area else n.get('m2')
    # паллетоместа: по объявлению или оценка (площадь × k × ярусы; от 9,5 м — не меньше 5 ярусов)
    if n.get('pm_stated'):
        x['pm'], x['pm_how'], x['pm_cit'] = n['pm_stated'], 'объявление', n.get('pm_cit', 'по объявлению')
    elif sklad and h:
        tiers = max(1, round(h / D['tier']))
        if h >= 9.5:
            tiers = max(tiers, 5)
        x['pm'] = int(round(sklad * D['k'] * tiers, -1))
        x['pm_how'] = 'оценка'
        x['pm_cit'] = f"складская площадь по объявлению {sp(sklad)} м² × {comma(D['k'])} ПМ/м² на ярус × {tiers} яр. (высота {comma(h)} м)"
    else:
        x['pm'], x['pm_how'], x['pm_cit'] = None, '', 'нет площади' if not sklad else 'нет высоты'
    x['pmm'] = round(x['rub'] / x['pm']) if x['rub'] and x['pm'] else None
    # причины
    why, zap = [], []
    if x['zhd'] == 'N':
        why.append('ж/д нет')
    elif x['zhd'] == 'B':
        why.append('ж/д: тупик рядом, рампы нет — разгрузка на улице')
    elif x['zhd_weak']:
        why.append('ж/д с оговоркой (не действует, далеко или чужая)')
    if x['kind'] != 'склад':
        why.append('производство, не склад' if x['kind'] == 'производство' else f"{x['kind']}, не склад")
    if h is None:
        zap.append('высота не указана — нужна от 9,5 м')
    elif h < 9.5:
        why.append(f'высота {comma(h)} м — меньше 9,5')
    if x['klass'] and x['klass'][0] not in 'AB':
        why.append(f"класс {x['klass']}")
    if x['rayon'] not in ('Кировский', 'Ленинский'):
        why.append('район не Кировский и не Ленинский' if x['city'] else 'место: за городом')
    if x['pm'] is None:
        zap.append('паллетоместа не посчитать: ' + x['pm_cit'])
    elif x['pm'] < 6000:
        why.append('меньше 6 000 паллетомест')
    elif x['pm'] < 8000:
        zap.append(f"не хватает {sp(8000 - x['pm'])} ПМ")
    x['why'], x['zap'], x['note'] = why, zap, ''
    # баллы: те же веса, что на странице (ж/д 15, вместимость 20, место 20, цена 20, пиво 15, доки и класс 10)
    zh = {'A': 15, 'B': 8, 'N': 0}[x['zhd']]
    if x['zhd_weak']:
        zh = {15: 8, 8: 4, 0: 0}[zh]
    pm = x['pm']
    cap = 0 if pm is None else 20 if pm >= 10000 else 14 if pm >= 8000 else 2 if pm >= 6000 else 0
    cap_t = 'нет данных' if pm is None else f"{sp(pm)} ПМ ({'оценка' if x['pm_how'] == 'оценка' else 'по объявлению'}); " + \
        ('ещё +2 000 возможны' if pm >= 10000 else 'запаса на +2 000 не видно')
    km = x['kmb']
    loc = 20 if x['city'] else 0 if km is None or km > 20 else 12 if km <= 5 else 8 if km <= 10 else 4
    beer = {'да': 6, 'частично': 3}.get(x['teplo'], 0) + (5 if h and h >= 10 else 2 if h and h >= 7 else 0) + \
        (2 if x['bespyl'] else 0) + (2 if x['nagr'] and x['nagr'] >= 5 else 0)
    beer_t = f"тепло: {x['teplo'] or 'нет данных'}; высота: {comma(h) + ' м' if h else 'нет данных'}; пол: " + \
        (', '.join(filter(None, ['беспыльный' if x['bespyl'] else '', f"{comma(x['nagr'])} т/м²" if x['nagr'] else ''])) or 'нет данных')
    dk = (5 if x['doki'] and x['doki'] >= 4 else 3 if x['doki'] else 0) + {'A': 5, 'B': 3}.get((x['klass'] or ' ')[0], 0)
    x['parts'] = [
        ['Ж/д', {'A': 'рампа или пандус у ветки', 'B': 'ветка на территории, рампы в тексте нет', 'N': 'нет'}[x['zhd']] +
         (' (с оговоркой)' if x['zhd_weak'] else ''), zh],
        ['Вместимость', cap_t, cap],
        ['Место', x['kmb_how'], loc],
        price_part(x, D['med']),
        ['Для пива', beer_t, min(15, beer)],
        ['Доки и класс', f"доков: {x['doki'] or 'нет данных'}; класс: {x['klass'] or 'нет данных'}", dk],
    ]
    x['score'] = sum(p[2] for p in x['parts'])
    return x


def reason(w):
    w = re.sub(r' \([^)]*\d\d\.\d\d\.\d{4}\)$', '', w)
    return 'высота меньше 9,5 м' if w.startswith('высота ') else w


def patch_template(html):
    """Правки вёрстки под актуализацию. Каждая применяется один раз."""
    def once(old, new):
        nonlocal html
        if new in html:
            return
        assert html.count(old) == 1, ('шаблон изменился, не найдено', old[:70], html.count(old))
        html = html.replace(old, new)

    html = re.sub(r'<title>[^<]*</title>', '<title>Склад под пиво — подбор, обновляется по понедельникам</title>', html, count=1)
    html = re.sub(r'<h1>[^<]*</h1>', '<h1>Склад под пиво · <span id="asof"></span></h1>', html, count=1)
    once("$('#meta').innerHTML =", "$('#asof').textContent = 'проверено ' + D.checked;\n$('#meta').innerHTML =")
    once(" Склад на Петухова стоит первым, хотя объявлению больше 3 месяцев. Собрано ${esc(D.built)}, условия уточнены ${esc(D.built2)}.`;",
         " Склад на Петухова стоит первым. Собрано ${esc(D.built)}, условия уточнены ${esc(D.built2)}. <b>Проверено ${esc(D.checked)}</b>: ${esc(D.log[0].t)}`;")
    once("${x.note ? `<div class=\"vwhy v-zapas\"><h4>Важно</h4><p>${esc(x.note)}</p></div>` : ''}",
         "${x.note ? `<div class=\"vwhy v-zapas\"><h4>Важно</h4><p>${esc(x.note)}</p></div>` : ''}"
         "${x.chk ? `<div class=\"vwhy ${x.chk.st === 'активно' ? 'v-final' : 'v-zapas'}\"><h4>Проверка ${esc(x.chk.d)}: ${esc(x.chk.st)}</h4><p>${esc(x.chk.t)}</p></div>` : ''}")
    once('<img loading="lazy" alt="Карта" src="${x.mapimg}">', '${x.mapimg ? `<img loading="lazy" alt="Карта" src="${x.mapimg}">` : \'\'}')
    once('<span class="tags"><span class="rank">№${x.rank}</span>',
         '<span class="tags"><span class="rank">№${x.rank}</span>${x.added ? `<span class="verdict v-zapas">новое ${esc(x.added)}</span>` : \'\'}')
    once("<p class=\"why\">Звонков, заявок и регистраций не было. Цены и параметры — как в объявлениях на дату сбора.</p>`;",
         "<p><b>Актуализация по понедельникам.</b> Раз в неделю проверяется, висят ли объявления из финала и запаса и не изменилась ли цена, и ищутся новые объявления под те же условия. "
         "Домклик, Циан, Авито и Яндекс Недвижимость закрыты для автоматического чтения, поэтому проверка идёт по зеркалу объявлений (arendacre.mirkvartir.ru), каталогам и поисковой выдаче; в карточке написано, как именно проверено. "
         "Возраст объявления считается от даты его последнего обновления на день проверки. Объявления из отсева повторно не открываются — их параметры остались на дату сбора.</p>"
         "<h2>Журнал обновлений</h2><div class=\"tablewrap\"><table><tr><th>Дата</th><th>Что изменилось</th></tr>${D.log.map(l => `<tr><td>${esc(l.d)}</td><td>${esc(l.t)}</td></tr>`).join('')}</table></div>\n"
         "<p class=\"why\">Звонков, заявок и регистраций не было. Цены и параметры — как в объявлениях на дату сбора или последней проверки.</p>`;")
    return html


def main(upd_path, html_path=HTML):
    U = json.load(open(upd_path, encoding='utf-8'))
    today = dt.date.fromisoformat(U['date'])
    today_ru = ru(U['date'])
    cutoff = minus_3_months(today).isoformat()
    html = open(html_path, encoding='utf-8').read()
    m = re.search(r'(<script id="data" type="application/json">)(.*?)(</script>)', html, re.S)
    D = json.loads(m.group(2))
    L = D['items']
    by = {x['key']: x for x in L}
    before = {x['key']: x['verdict'] for x in L}

    # 1. новые объявления
    D.setdefault('total0', D['total'])
    for n in U.get('new', []):
        n.setdefault('added', today_ru)
        if n['key'] in by:
            n['added'] = by[n['key']].get('added') or n['added']
            L.remove(by[n['key']])
        x = new_item(n, D)
        if n['added'] == today_ru:
            x['chk'] = {'d': today_ru, 'st': 'активно', 't': 'Новое объявление, открыто в день проверки.'}
        L.append(x)
        by[x['key']] = x
    D['total'] = D['total0'] + sum(1 for x in L if x.get('added'))
    D['uniq'] = len(L)

    # 2. результаты проверки
    for c in U.get('checks', []):
        for k in c['keys']:
            x = by[k]
            t = c.get('how', '')
            if c.get('rub') and x.get('rub') and c['rub'] != x['rub']:
                t += f" Цена изменилась: было {sp(x['rub'])} ₽ в месяц, стало {sp(c['rub'])} ₽."
                x['rub'] = c['rub']
                x['m2'] = round(x['rub'] / x['area']) if x.get('area') else x['m2']
                x['pmm'] = round(x['rub'] / x['pm']) if x.get('pm') else x.get('pmm')
                rescore(x, D['med'])
            if c.get('upd'):
                x['upd'] = max(c['upd'], x.get('upd') or '')
            x['chk'] = {'d': today_ru, 'st': c['status'], 't': t.strip()}
    # 3. вердикты: свежесть на дату проверки и снятые объявления
    for x in L:
        why = [w for w in x['why'] if not w.startswith((STALE, GONE))]
        fresh = max(filter(None, [date_iso(x['date']), x.get('upd')]), default=None)
        note = re.sub(r'Объявление от \d\d\.\d\d\.\d{4} — старше 3 месяцев(?:, но \d\d\.\d\d\.\d{4} ещё висело)?\.+\s*(Проверить, сдаётся ли и по какой цене\.\s*)?', '', x.get('note') or '')
        note = re.sub(r'Дата объявления не указана — уточнить, актуально ли\.\s*', '', note)
        if x.get('manual_note') and x['manual_note'] not in note:
            note = (x['manual_note'] + ' ' + note).strip()
        if fresh and fresh < cutoff:
            if x.get('pet'):
                note = f'Объявление от {ru(fresh)} — старше 3 месяцев. Проверить, сдаётся ли и по какой цене. ' + note
            else:
                why.append(f'{STALE} ({ru(fresh)})')
        elif not fresh:
            note = 'Дата объявления не указана — уточнить, актуально ли. ' + note
        if (x.get('chk') or {}).get('st') == 'снято':
            why.append(f"{GONE} (проверка {x['chk']['d']})")
        x['why'], x['note'] = why, note.strip()
        x['verdict'] = 'отсев' if why else ('запас' if x['zap'] else 'финал')

    for x in L:
        if x['verdict'] != 'отсев' and (x.get('chk') or {}).get('d') != today_ru:
            x['chk'] = {'d': today_ru, 'st': 'не проверено',
                        't': 'Площадка закрыта для автоматической проверки, на зеркалах объявление не нашлось. Откройте объявление и убедитесь, что оно ещё висит.'}

    L.sort(key=lambda x: (ORDER[x['verdict']], not (x.get('pet') and x['verdict'] != 'отсев'), -x['score']))
    for i, x in enumerate(L, 1):
        x['rank'] = i
    live = {x['key']: x for x in L}
    for x in L:   # соседи по комплексу: обновить вердикты в ссылках
        x['sosedi'] = [[s[0], s[1], live[s[0]]['verdict']] for s in x.get('sosedi', []) if s[0] in live]
    D['cnt'] = dict(collections.Counter(x['verdict'] for x in L))
    D['otsev'] = [list(kv) for kv in collections.Counter(reason(w) for x in L if x['verdict'] == 'отсев' for w in x['why']).most_common()]
    D['checked'] = today_ru
    D['log'] = [{'d': today_ru, 't': U['summary']}] + [l for l in D.get('log', []) if l['d'] != today_ru]

    js = json.dumps(D, ensure_ascii=False).replace('</', '<\\/')
    html = html[:m.start(2)] + js + html[m.end(2):]
    html = patch_template(html)
    open(html_path, 'w', encoding='utf-8', newline='\n').write(html)

    print('проверено', today_ru, '| порог свежести', ru(cutoff), '|', D['cnt'])
    for x in L:
        was = before.get(x['key'], 'нет')
        if x['verdict'] != 'отсев' or was != x['verdict']:
            print(f"{x['rank']:>3} {x['verdict']:<5} (было: {was}) {x['score']:>3} {x['key']} {x['place'][:50]} | {sp(x['rub']) if x.get('rub') else '—'} ₽ | "
                  f"{(x.get('chk') or {}).get('st', '')} | {'; '.join(x['why'] + x['zap'])[:90]}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main(*sys.argv[1:])
