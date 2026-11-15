"""JEO QUIZ — jonli server va Gemini AI integratsiyasi (parallel tezkor versiya)."""
import json, os, random, socket, sys, threading, collections, glob
import concurrent.futures
import urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))

def load_dotenv():
    env_file = os.path.join(BASE, '.env')
    if os.path.exists(env_file):
        with open(env_file, encoding='utf8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv()

PORT = int(os.environ.get('PORT', 8000))
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash').strip()

def resolve_qs_path():
    if len(sys.argv) > 1:
        return os.path.join(BASE, sys.argv[1])
    default = os.path.join(BASE, 'questions.json')
    if os.path.exists(default):
        return default
    jsons = sorted(glob.glob(os.path.join(BASE, '*.json')))
    return jsons[0] if jsons else default

QS_PATH = resolve_qs_path()
QS = json.load(open(QS_PATH, encoding='utf8'))

def check_quiz(qs):
    """25 ta savol, 5 kategoriya, har kategoriyada 100..500. Qaytaradi: (xatolar, cats, c_taqsimoti)"""
    errors = []
    if len(qs) != 25:
        errors.append(f'Savollar soni 25 bo‘lishi kerak, hozir {len(qs)} ta')
        return errors, [], {}
    cats = []
    for q in qs:
        if q['cat'] not in cats:
            cats.append(q['cat'])
    if len(cats) != 5:
        errors.append(f'Kategoriyalar soni 5 bo‘lishi kerak, hozir {len(cats)} ta')
    for i, q in enumerate(qs):
        want_cat = cats[i // 5] if len(cats) == 5 else None
        want_pts = (i % 5 + 1) * 100
        if q['cat'] != want_cat or q['pts'] != want_pts:
            errors.append(f'{i+1}-savol: kategoriya yoki ball tartibi noto‘g‘ri ({q["cat"]}, {q["pts"]})')
    dist = collections.Counter(q['c'] for q in qs if q.get('opts'))
    return errors, cats, dist

_errs, _cats, _dist = check_quiz(QS)
if _errs:
    print('XATO: quiz fayli noto‘g‘ri:')
    for e in _errs:
        print('  -', e)
    sys.exit(1)

PIN = str(os.environ.get('ADMIN_PIN', '4000'))
lock = threading.Lock()
state = {
    'teams': ['1-jamoa', '2-jamoa', '3-jamoa', '4-jamoa'],
    'scores': [0, 0, 0, 0],
    'cur': None, 'revealed': False,
    'used': [False] * len(QS),
    'answers': {},
    'text_answers': {},
    'ai_grades': {},
    'ai_note': '',
    'players': {},
    'shown_opts': [], 'shown_c': None,
}

def call_gemini(prompt, json_mode=False, temperature=0.7):
    api_key = os.environ.get('GEMINI_API_KEY', '').strip() or GEMINI_API_KEY
    model = os.environ.get('GEMINI_MODEL', '').strip() or GEMINI_MODEL
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY topilmadi. Render yoki .env fayliga kalitni kiriting.')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    gen_cfg = {'temperature': temperature}
    if json_mode:
        gen_cfg['responseMimeType'] = 'application/json'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': gen_cfg
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode('utf8'))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf8', errors='ignore')
        raise RuntimeError(f'Gemini API xatosi ({e.code}): {err_body[:180]}')
    except Exception as e:
        raise RuntimeError(f'Gemini serveriga ulanib bo‘lmadi: {e}')

    try:
        text = raw['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception:
        raise RuntimeError('Gemini kutilmagan javob qaytardi')

    if json_mode:
        if text.startswith('```'):
            text = text.strip('`')
            if text.startswith('json'):
                text = text[4:].strip()
        return json.loads(text)
    return text

def ai_generate_category(topic, cname, level):
    prompt = f"""O‘zbek tilida "Jeo Quiz" o‘yini uchun "{topic}" mavzusining "{cname}" bo‘limiga ({level}) 5 ta test savoli tuz (100, 200, 300, 400, 500 ball).
Faqat quyidagi JSON formatida qaytar:
{{
  "questions": [
    {{"pts": 100, "q": "Qisqa savol", "opts": ["A", "B", "C", "D"], "c": 0, "exp": "1 gaplik izoh"}}
  ]
}}
Qoidalar: ketma-ket 100, 200, 300, 400, 500 ballik 5 ta savol, 4 ta qisqa variant, "c" (0..3) turlicha bo‘lsin, matnlar ixcham va ravon o‘zbek tilida bo‘lsin."""
    data = call_gemini(prompt, json_mode=True, temperature=0.7)
    qs_list = data.get('questions') or []
    if len(qs_list) != 5:
        raise RuntimeError(f'"{cname}" bo‘limida 5 ta savol chiqmadi')
    cat_qs = []
    for idx, item in enumerate(qs_list):
        opts = [str(x).strip() for x in (item.get('opts') or [])][:4]
        if len(opts) < 4:
            raise RuntimeError('Variantlar to‘liq shakllanmadi')
        c = int(item.get('c', 0))
        if not (0 <= c < 4):
            c = 0
        cat_qs.append({
            'cat': cname,
            'pts': (idx + 1) * 100,
            'q': str(item.get('q', '')).strip(),
            'opts': opts,
            'c': c,
            'exp': str(item.get('exp', 'Izoh')).strip()
        })
    return cat_qs

def ai_generate_board(topic, level='universitet talabalari'):
    cat_prompt = f"""O‘zbek tilida "{topic}" mavzusi ({level}) bo‘yicha intellektual viktorina uchun 5 ta alohida sub-kategoriya nomini tuz.
Faqat quyidagi JSON formatida qaytar:
{{"categories": ["1-bo‘lim", "2-bo‘lim", "3-bo‘lim", "4-bo‘lim", "5-bo‘lim"]}}
Har bir nom 1-3 so‘zdan iborat qisqa va o‘zbek tilida bo‘lsin."""
    cat_data = call_gemini(cat_prompt, json_mode=True, temperature=0.7)
    raw_cats = [str(x).strip()[:35] for x in (cat_data.get('categories') or []) if str(x).strip()]
    cats = []
    for c in raw_cats:
        if c not in cats:
            cats.append(c)
    if len(cats) < 5:
        raise RuntimeError('AI 5 ta kategoriya tuza olmadi, qayta urinib ko‘ring')
    cats = cats[:5]

    result = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(ai_generate_category, topic, cname, level) for cname in cats]
        for fut in futures:
            result.extend(fut.result())

    errs, new_cats, _ = check_quiz(result)
    if errs:
        raise RuntimeError('AI generatsiya tekshiruvidan o‘tmadi: ' + errs[0])
    return result, new_cats

def ai_generate_single(cat, pts, hint=''):
    prompt = f"""O‘zbek tilidagi "Jeo Quiz" o‘yini uchun BITTA test savoli tuz.
Kategoriya: "{cat}", qiyinlik darajasi: {pts} ball (100 - eng oson, 500 - eng qiyin).
Qo‘shimcha ko‘rsatma: "{hint or 'mavzuga mos qiziqarli savol'}".
Faqat quyidagi JSON obyektini qaytar:
{{
  "q": "Savol matni",
  "opts": ["1-variant", "2-variant", "3-variant", "4-variant"],
  "c": 1,
  "exp": "Qisqa izoh"
}}"""
    item = call_gemini(prompt, json_mode=True, temperature=0.8)
    opts = [str(x).strip() for x in (item.get('opts') or [])][:4]
    c = int(item.get('c', 0))
    if len(opts) < 2 or not (0 <= c < len(opts)):
        raise RuntimeError('AI to‘g‘ri formatda savol tuza olmadi')
    return {
        'cat': cat,
        'pts': pts,
        'q': str(item.get('q', '')).strip(),
        'opts': opts,
        'c': c,
        'exp': str(item.get('exp', '')).strip()
    }

def ai_explain_question(q):
    ans = q['opts'][q['c']] if q.get('opts') else q.get('ans', '')
    prompt = f"""Talabalar uchun o‘zbek tilida qisqa va esda qolarli tushuntirish yoz (maksimum 2-3 gap).
Savol: {q['q']}
To‘g‘ri javob: {ans}
Asosiy izoh: {q.get('exp', '')}
Vazifa: Bu tushunchani real hayotiy misol yoki oson mantiq bilan tushuntirib ber."""
    return call_gemini(prompt, json_mode=False, temperature=0.6)

def ai_grade_short_answers(q, teams, text_answers):
    submitted = {str(t): text_answers[t] for t in text_answers if str(text_answers[t]).strip()}
    if not submitted:
        return {}
    prompt = f"""Sen o‘qituvchi yordamchisisisan. Jamoalarning qisqa yozma javoblarini etalon javob bilan solishtirib bahola.
Savol: {q['q']}
Etalon to‘g‘ri javob: {q.get('ans', '')}
Izoh: {q.get('exp', '')}
Jamoalar javoblari (indeks: javob): {json.dumps(submitted, ensure_ascii=False)}

Har bir jamoa indeksi uchun quyidagi JSON formatida natija qaytar:
{{
  "0": {{"percent": 90, "verdict": "To‘g‘ri", "comment": "Qisqa izoh (1 gap)"}},
  "1": {{"percent": 40, "verdict": "Qisman", "comment": "Qisqa izoh (1 gap)"}}
}}"""
    res = call_gemini(prompt, json_mode=True, temperature=0.2)
    return res if isinstance(res, dict) else {}

def save_questions():
    path = QS_PATH
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8') as f:
        json.dump(QS, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)

def clean_question(d, old):
    text = str(d.get('q', '')).strip()
    exp = str(d.get('exp', '')).strip()
    if len(text) < 5:
        return None, 'Savol matnini to‘liq yozing'
    if not exp:
        return None, 'Izohni yozing'
    base = {'cat': old['cat'], 'pts': old['pts'], 'q': text, 'exp': exp}
    if d.get('short'):
        ans = str(d.get('ans', '')).strip()
        if not ans:
            return None, 'Qisqa javobni yozing'
        base.update(opts=[], ans=ans)
        return base, None
    raw = [str(o).strip() for o in (d.get('opts') or [])][:4]
    c = d.get('c')
    if not (isinstance(c, int) and 0 <= c < len(raw) and raw[c]):
        return None, 'To‘g‘ri variantni belgilang'
    pairs = [(o, i) for i, o in enumerate(raw) if o]
    if len(pairs) < 2:
        return None, 'Kamida 2 ta variant kerak'
    opts = [o for o, _ in pairs]
    base.update(opts=opts, c=[k for k, (o, i) in enumerate(pairs) if i == c][0])
    return base, None

def public_state(admin=False):
    s = {
        'cats': _cats, 'teams': state['teams'], 'scores': state['scores'],
        'used': state['used'], 'revealed': state['revealed'],
        'cur': state['cur'], 'total': len(QS), 'ai_note': state['ai_note']
    }
    if state['cur'] is not None:
        q = QS[state['cur']]
        qq = {'cat': q['cat'], 'pts': q['pts'], 'q': q['q'], 'opts': state['shown_opts']}
        if state['revealed'] or admin:
            qq['c'] = state['shown_c']
            qq['ans'] = q.get('ans')
            qq['exp'] = q['exp']
        s['question'] = qq
    if admin:
        s['answers'] = {str(k): v for k, v in state['answers'].items()}
        s['text_answers'] = {str(k): v for k, v in state['text_answers'].items()}
        s['ai_grades'] = state['ai_grades']
        s['ai_ready'] = bool(os.environ.get('GEMINI_API_KEY', '').strip() or GEMINI_API_KEY)
        s['players'] = [{'name': n, 'team': t} for n, t in state['players'].items()]
    return s

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80)); ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        b = body if isinstance(body, bytes) else body.encode('utf8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8')

    def _file(self, name):
        with open(os.path.join(BASE, name), 'rb') as f:
            self._send(200, f.read(), 'text/html; charset=utf-8')

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            return self._file('index.html')
        if u.path == '/admin':
            return self._file('admin.html')
        if u.path == '/api/questions':
            if parse_qs(u.query).get('pin', [''])[0] != PIN:
                return self._json({'error': 'PIN noto‘g‘ri'}, 403)
            with lock:
                return self._json(QS)
        if u.path == '/api/state':
            qs = parse_qs(u.query)
            if qs.get('admin') == ['1']:
                if qs.get('pin', [''])[0] != PIN:
                    return self._json({'error': 'PIN noto‘g‘ri'}, 403)
                with lock:
                    return self._json(public_state(admin=True))
            with lock:
                return self._json(public_state())
        self._send(404, 'Topilmadi', 'text/plain; charset=utf-8')

    def do_POST(self):
        global QS, _cats
        n = int(self.headers.get('Content-Length', 0) or 0)
        try:
            data = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self._json({'error': 'Noto‘g‘ri so‘rov'}, 400)
        p = urlparse(self.path).path

        if p == '/api/login':
            with lock:
                name = str(data.get('name', '')).strip()[:30]
                if len(name) < 2:
                    return self._json({'error': 'Ism kamida 2 harf bo‘lishi kerak'}, 400)
                t = data.get('team')
                if not (isinstance(t, int) and 0 <= t < len(state['teams'])):
                    t = None
                state['players'][name] = t
                return self._json({'ok': True})

        if p == '/api/answer':
            with lock:
                t = data.get('team')
                cur = state['cur']
                if cur is None or state['revealed']:
                    return self._json({'error': 'Hozir javob qabul qilinmaydi'}, 400)
                if not (isinstance(t, int) and 0 <= t < len(state['teams'])):
                    return self._json({'error': 'Noto‘g‘ri jamoa'}, 400)
                opts = state['shown_opts']
                if not opts:
                    txt = str(data.get('text', '')).strip()[:250]
                    if not txt:
                        return self._json({'error': 'Javob matnini yozing'}, 400)
                    if t not in state['text_answers']:
                        state['text_answers'][t] = txt
                    return self._json({'ok': True})
                c = data.get('choice')
                if not (isinstance(c, int) and 0 <= c < len(opts)):
                    return self._json({'error': 'Noto‘g‘ri ma‘lumot'}, 400)
                if t not in state['answers']:
                    state['answers'][t] = c
                return self._json({'ok': True})

        if p == '/api/admin':
            if data.get('pin') != PIN:
                return self._json({'error': 'PIN noto‘g‘ri'}, 403)
            act = data.get('action')

            if act == 'ai_generate_board':
                topic = str(data.get('topic', '')).strip()
                level = str(data.get('level', 'universitet talabalari')).strip()
                if len(topic) < 3:
                    return self._json({'error': 'Mavzu nomini kamida 3 harf bilan yozing'}, 400)
                try:
                    new_qs, new_cats = ai_generate_board(topic, level)
                except Exception as e:
                    return self._json({'error': str(e)}, 500)
                with lock:
                    QS = new_qs
                    _cats = new_cats
                    try:
                        save_questions()
                    except Exception:
                        pass
                    state.update(
                        cur=None, revealed=False, used=[False] * len(QS),
                        answers={}, text_answers={}, ai_grades={}, ai_note=''
                    )
                    return self._json(public_state(admin=True))

            if act == 'ai_generate_slot':
                idx = data.get('idx')
                hint = str(data.get('hint', '')).strip()
                with lock:
                    if not (isinstance(idx, int) and 0 <= idx < len(QS)):
                        return self._json({'error': 'Noto‘g‘ri katakcha'}, 400)
                    cat, pts = QS[idx]['cat'], QS[idx]['pts']
                try:
                    gen_q = ai_generate_single(cat, pts, hint)
                except Exception as e:
                    return self._json({'error': str(e)}, 500)
                return self._json({'ok': True, 'question': gen_q})

            if act == 'ai_explain':
                with lock:
                    if state['cur'] is None:
                        return self._json({'error': 'Avval savolni oching'}, 400)
                    q_copy = dict(QS[state['cur']])
                try:
                    note = ai_explain_question(q_copy)
                except Exception as e:
                    return self._json({'error': str(e)}, 500)
                with lock:
                    state['ai_note'] = note
                    return self._json(public_state(admin=True))

            if act == 'ai_grade':
                with lock:
                    if state['cur'] is None:
                        return self._json({'error': 'Avval savolni oching'}, 400)
                    q_copy = dict(QS[state['cur']])
                    teams_copy = list(state['teams'])
                    txt_copy = dict(state['text_answers'])
                if not txt_copy:
                    return self._json({'error': 'Hali hech bir jamoa yozma javob yubormagan'}, 400)
                try:
                    grades = ai_grade_short_answers(q_copy, teams_copy, txt_copy)
                except Exception as e:
                    return self._json({'error': str(e)}, 500)
                with lock:
                    state['ai_grades'] = grades
                    return self._json(public_state(admin=True))

            with lock:
                if act == 'open':
                    idx = data.get('idx')
                    if isinstance(idx, int) and 0 <= idx < len(QS):
                        q = QS[idx]
                        n = len(q['opts'])
                        perm = list(range(n))
                        random.shuffle(perm)
                        state['shown_opts'] = [q['opts'][i] for i in perm]
                        state['shown_c'] = perm.index(q['c']) if n else None
                        state.update(
                            cur=idx, revealed=False, answers={},
                            text_answers={}, ai_grades={}, ai_note=''
                        )
                        state['used'][idx] = True
                elif act == 'save':
                    idx = data.get('idx')
                    if not (isinstance(idx, int) and 0 <= idx < len(QS)):
                        return self._json({'error': 'Noto‘g‘ri katakcha'}, 400)
                    if state['cur'] == idx:
                        return self._json({'error': 'Bu savol hozir ochiq. Avval uni yoping'}, 400)
                    new, err = clean_question(data.get('q') or {}, QS[idx])
                    if err:
                        return self._json({'error': err}, 400)
                    QS[idx] = new
                    try:
                        save_questions()
                    except Exception as e:
                        return self._json({'error': 'Faylga saqlashda xato: ' + str(e)}, 500)
                elif act == 'reveal':
                    if state['cur'] is not None:
                        state['revealed'] = True
                elif act == 'close':
                    state.update(
                        cur=None, revealed=False, answers={},
                        text_answers={}, ai_grades={}, ai_note=''
                    )
                elif act == 'award' and state['cur'] is not None:
                    t, sign = data.get('team'), data.get('sign', 1)
                    if isinstance(t, int) and 0 <= t < 4:
                        state['scores'][t] += sign * QS[state['cur']]['pts']
                elif act == 'score':
                    t, d = data.get('team'), data.get('delta')
                    if isinstance(t, int) and 0 <= t < 4 and isinstance(d, int):
                        state['scores'][t] += d
                elif act == 'rename':
                    names = data.get('teams')
                    if isinstance(names, list) and len(names) == 4:
                        state['teams'] = [str(x)[:30] or f'Jamoa {i+1}' for i, x in enumerate(names)]
                elif act == 'reset':
                    state.update(
                        scores=[0, 0, 0, 0], cur=None, revealed=False,
                        used=[False] * len(QS), answers={},
                        text_answers={}, ai_grades={}, ai_note=''
                    )
                else:
                    return self._json({'error': 'Noma‘lum amal'}, 400)
                return self._json(public_state(admin=True))

        self._send(404, 'Topilmadi', 'text/plain; charset=utf-8')

if __name__ == '__main__':
    ip = local_ip()
    ai_status = f'ULANGAN ({GEMINI_MODEL})' if GEMINI_API_KEY else 'ULANMAGAN (GEMINI_API_KEY yo‘q)'
    print('=' * 56)
    print(f'  Quiz fayli: {os.path.basename(QS_PATH)}  ({len(QS)} savol)')
    letters = ['A', 'B', 'C', 'D']
    print('  To‘g‘ri javoblar: ' + '  '.join(f'{letters[k]}={_dist.get(k, 0)}' for k in range(4)))
    print(f'  Gemini AI:  {ai_status}')
    print('  JEO QUIZ server ishga tushdi')
    print(f'  O‘quvchilar uchun:  http://{ip}:{PORT}')
    print(f'  O‘qituvchi paneli:  http://{ip}:{PORT}/admin')
    print(f'  Admin PIN:          {PIN}')
    print('  To‘xtatish: Ctrl+C')
    print('=' * 56)
    try:
        srv = QuietServer(('0.0.0.0', PORT), H)
    except OSError:
        print(f'\nXATO: {PORT}-port band. Avval eski serverni to‘xtating (Ctrl+C).')
        sys.exit(1)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
