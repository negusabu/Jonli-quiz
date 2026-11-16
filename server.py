"""JEO QUIZ — jonli server va barqaror Gemini AI integratsiyasi."""
import json, os, random, re, socket, sys, threading, collections, glob, time
import urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
API_BASE = 'https' + '://generativelanguage.googleapis.com/v1beta/models'

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
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', '').strip()

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
            errors.append(f'{i+1}-savol: kategoriya yoki ball tartibi noto‘g‘ri')
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
    'ai_busy': False,
    'ai_status': '',
    'ai_error': '',
    'players': {},
    'shown_opts': [], 'shown_c': None,
}

def extract_json_obj(text):
    text = text.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        text = '\n'.join(lines).strip()
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text, strict=False)
    except Exception:
        cleaned = re.sub(r',\s*([}\]])', r'\1', text)
        return json.loads(cleaned, strict=False)

def discover_models(api_key):
    url = f'{API_BASE}?key={api_key}'
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf8'))
        found = []
        for m in data.get('models', []):
            methods = m.get('supportedGenerationMethods', [])
            name = m.get('name', '').replace('models/', '')
            if 'generateContent' in methods and any(k in name for k in ('flash', 'gemma')):
                if not any(bad in name for bad in ('tts', 'image', 'audio', 'vision', 'embedding', '2.5-flash-lite')):
                    found.append(name)
        return found
    except Exception:
        return []

def call_gemini(prompt, json_mode=False, temperature=0.6):
    api_key = os.environ.get('GEMINI_API_KEY', '').strip() or GEMINI_API_KEY
    primary = os.environ.get('GEMINI_MODEL', '').strip() or GEMINI_MODEL
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY topilmadi.')

    base_list = [
        'gemini-flash-lite-latest',
        'gemini-3.1-flash-lite-preview',
        'gemini-flash-latest',
        'gemini-2.5-flash',
        'gemini-3-flash-preview',
        primary,
        'gemma-3-27b-it',
    ]
    candidates = []
    for m in base_list:
        if m and m != 'gemini-2.5-flash-lite' and m not in candidates:
            candidates.append(m)

    raw = None
    real_err = None
    fallback_err = 'AI javob bermadi'

    def try_models(model_list):
        nonlocal raw, real_err, fallback_err
        for model in model_list:
            url = f'{API_BASE}/{model}:generateContent?key={api_key}'
            is_gemma = model.startswith('gemma')
            think_mode = 'none' if is_gemma else ('minimal' if 'gemini-3' in model else 'zero')

            for attempt in range(2):
                gen_cfg = {'temperature': temperature, 'maxOutputTokens': 4096}
                if json_mode and not is_gemma:
                    gen_cfg['responseMimeType'] = 'application/json'
                if think_mode == 'minimal':
                    gen_cfg['thinkingConfig'] = {'thinkingLevel': 'minimal'}
                elif think_mode == 'zero':
                    gen_cfg['thinkingConfig'] = {'thinkingBudget': 0}

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
                    with urllib.request.urlopen(req, timeout=55) as resp:
                        raw = json.loads(resp.read().decode('utf8'))
                        return
                except urllib.error.HTTPError as e:
                    err_body = e.read().decode('utf8', errors='ignore')
                    msg = f'API xatosi ({e.code}, {model}): {err_body[:130]}'
                    if e.code == 400 and think_mode != 'none':
                        think_mode = 'none'
                        continue
                    if e.code == 404:
                        fallback_err = msg
                        break
                    real_err = msg
                    if e.code in (500, 502, 503, 504) and attempt == 0:
                        time.sleep(1.5)
                        continue
                    break
                except Exception as e:
                    real_err = f'Ulanish xatosi ({model}): {e}'
                    break

    try_models(candidates)

    if raw is None:
        extra = [m for m in discover_models(api_key) if m not in candidates]
        if extra:
            try_models(extra[:4])

    if raw is None:
        final_err = real_err or fallback_err
        if '429' in final_err:
            raise RuntimeError('Bepul API limiti to‘ldi. 1 daqiqa kutib qayta bosing.')
        raise RuntimeError(final_err)

    try:
        text = raw['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception:
        raise RuntimeError('AI kutilmagan javob qaytardi')

    if json_mode:
        return extract_json_obj(text)
    return text

def ai_generate_category(topic, cname, level):
    prompt = f"""O‘zbek tilida "{topic}" mavzusining "{cname}" bo‘limi uchun ({level}) 5 ta qisqa test savoli tuz (100, 200, 300, 400, 500 ball).
FAQAT shu JSON formatida qaytar:
{{"s":[{{"q":"Savol matni","o":["A","B","C","D"],"c":0,"e":"1 gap izoh"}}]}}
Qoidalar:
- "s" da aynan 5 ta savol (100..500 ball), 4 ta qisqa variant, "c" (0..3) turlicha bo‘lsin;
- Savol, variant va izoh matni ichida qo‘shtirnoq (") belgisini umuman ishlatma (kerak bo‘lsa « » ishlat)."""
    last_e = None
    for _ in range(3):
        try:
            data = call_gemini(prompt, json_mode=True, temperature=0.6)
            qs_list = data.get('s') or data.get('questions') or []
            if len(qs_list) != 5:
                last_e = RuntimeError(f'"{cname}" bo‘limida 5 ta savol chiqmadi')
                continue
            cat_qs = []
            ok = True
            for idx, item in enumerate(qs_list):
                opts = [str(x).strip() for x in (item.get('o') or item.get('opts') or [])][:4]
                if len(opts) < 4:
                    ok = False
                    break
                c = int(item.get('c', 0))
                if not (0 <= c < 4):
                    c = 0
                cat_qs.append({
                    'cat': cname,
                    'pts': (idx + 1) * 100,
                    'q': str(item.get('q', '')).strip(),
                    'opts': opts,
                    'c': c,
                    'exp': str(item.get('e') or item.get('exp') or 'Izoh').strip()
                })
            if ok:
                return cat_qs
        except Exception as e:
            last_e = e
            time.sleep(0.6)
    raise RuntimeError(f'"{cname}" bo‘limida xato: {last_e}')

def bg_generate_board(topic, level):
    global QS, _cats
    try:
        with lock:
            state['ai_status'] = '5 ta kategoriya nomi tuzilmoqda...'
        cat_prompt = f"""O‘zbek tilida "{topic}" mavzusi ({level}) uchun 5 ta alohida bo‘lim nomini tuz.
Matn ichida qo‘shtirnoq (") ishlatma.
FAQAT shu JSONni qaytar: {{"categories":["1-nom","2-nom","3-nom","4-nom","5-nom"]}}"""
        cat_data = call_gemini(cat_prompt, json_mode=True, temperature=0.6)
        raw_cats = [str(x).strip()[:35] for x in (cat_data.get('categories') or []) if str(x).strip()]
        cats = []
        for c in raw_cats:
            if c not in cats:
                cats.append(c)
        if len(cats) < 5:
            raise RuntimeError('AI 5 ta kategoriya tuza olmadi, qayta urinib ko‘ring')
        cats = cats[:5]

        result = []
        for i, cname in enumerate(cats):
            with lock:
                state['ai_status'] = f'{i+1}/5-bo‘lim tuzilmoqda: {cname}...'
            cat_qs = ai_generate_category(topic, cname, level)
            result.extend(cat_qs)
            if i < 4:
                time.sleep(0.4)

        errs, new_cats, _ = check_quiz(result)
        if errs:
            raise RuntimeError(errs[0])

        with lock:
            QS = result
            _cats = new_cats
            try:
                save_questions()
            except Exception:
                pass
            state.update(
                cur=None, revealed=False, used=[False] * len(QS),
                answers={}, text_answers={}, ai_grades={}, ai_note='',
                ai_busy=False, ai_error='',
                ai_status=f'Tayyor! "{topic}" bo‘yicha 25 ta savol jadvalga yuklandi ✔'
            )
    except Exception as e:
        with lock:
            state['ai_busy'] = False
            state['ai_status'] = ''
            state['ai_error'] = str(e)

def ai_generate_single(cat, pts, hint=''):
    prompt = f"""O‘zbek tilida "{cat}" kategoriyasi uchun {pts} ballik BITTA test savoli tuz ({hint or 'qiziqarli savol'}).
Matn ichida qo‘shtirnoq (") ishlatma (kerak bo‘lsa « » ishlat).
FAQAT shu JSONni qaytar: {{"q":"Savol","opts":["A","B","C","D"],"c":1,"exp":"Qisqa izoh"}}"""
    item = call_gemini(prompt, json_mode=True, temperature=0.7)
    opts = [str(x).strip() for x in (item.get('opts') or [])][:4]
    c = int(item.get('c', 0))
    if len(opts) < 2 or not (0 <= c < len(opts)):
        raise RuntimeError('AI to‘g‘ri savol tuza olmadi')
    return {
        'cat': cat, 'pts': pts,
        'q': str(item.get('q', '')).strip(),
        'opts': opts, 'c': c,
        'exp': str(item.get('exp', '')).strip()
    }

def ai_explain_question(q):
    ans = q['opts'][q['c']] if q.get('opts') else q.get('ans', '')
    prompt = f"""Talabalar uchun o‘zbek tilida 2 gaplik hayotiy misol bilan tushuntir:
Savol: {q['q']} | Javob: {ans} | Izoh: {q.get('exp', '')}"""
    return call_gemini(prompt, json_mode=False, temperature=0.6)

def ai_grade_short_answers(q, text_answers):
    submitted = {str(t): text_answers[t] for t in text_answers if str(text_answers[t]).strip()}
    if not submitted:
        return {}
    prompt = f"""Javoblarni etalon bilan solishtir. Savol: {q['q']} | Etalon: {q.get('ans', '')}
Javoblar: {json.dumps(submitted, ensure_ascii=False)}
Matn ichida qo‘shtirnoq (") ishlatma.
FAQAT shu JSONni qaytar: {{"0":{{"percent":90,"verdict":"To‘g‘ri","comment":"1 gap izoh"}}}}"""
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
        s['ai_busy'] = state['ai_busy']
        s['ai_status'] = state['ai_status']
        s['ai_error'] = state['ai_error']
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
                with lock:
                    if state['ai_busy']:
                        return self._json({'error': 'AI hozir savol tuzmoqda, biroz kuting'}, 400)
                    state['ai_busy'] = True
                    state['ai_error'] = ''
                    state['ai_status'] = 'AI ishga tushdi...'
                threading.Thread(target=bg_generate_board, args=(topic, level), daemon=True).start()
                with lock:
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
                    txt_copy = dict(state['text_answers'])
                if not txt_copy:
                    return self._json({'error': 'Hali hech bir jamoa yozma javob yubormagan'}, 400)
                try:
                    grades = ai_grade_short_answers(q_copy, txt_copy)
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
    srv_url = 'http' + f'://{ip}:{PORT}/admin'
    print('=' * 52)
    print(f'  JEO QUIZ server: {srv_url}  (PIN: {PIN})')
    print('=' * 52)
    try:
        srv = QuietServer(('0.0.0.0', PORT), H)
    except OSError:
        sys.exit(1)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
