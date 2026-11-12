"""STATISTIKA QUIZ — jonli server. Kompyuterda ishga tushiriladi, o'quvchilar Wi-Fi orqali ulanadi."""
import json, os, random, socket, sys, threading, secrets, collections
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT', 8000))
QS_PATH = os.path.join(BASE, sys.argv[1] if len(sys.argv) > 1 else 'questions.json')
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

PIN = str(secrets.randbelow(9000) + 1000)
lock = threading.Lock()
state = {
    'teams': ['1-jamoa', '2-jamoa', '3-jamoa', '4-jamoa'],
    'scores': [0, 0, 0, 0],
    'cur': None, 'revealed': False,
    'used': [False] * len(QS),
    'answers': {},
    'players': {},
    'shown_opts': [], 'shown_c': None,
}

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
    s = {'cats': _cats, 'teams': state['teams'], 'scores': state['scores'], 'used': state['used'],
         'revealed': state['revealed'], 'cur': state['cur'], 'total': len(QS)}
    if state['cur'] is not None:
        q = QS[state['cur']]
        qq = {'cat': q['cat'], 'pts': q['pts'], 'q': q['q'], 'opts': state['shown_opts']}
        if state['revealed'] or admin:
            qq['c'] = state['shown_c']; qq['ans'] = q.get('ans'); qq['exp'] = q['exp']
        s['question'] = qq
    if admin:
        s['answers'] = {str(k): v for k, v in state['answers'].items()}
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
    """Mijoz uzilib qolganda (ConnectionAbortedError, BrokenPipeError) xatolikni terminalga chiqarmaydi."""
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
        n = int(self.headers.get('Content-Length', 0) or 0)
        try:
            data = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self._json({'error': 'Noto‘g‘ri so‘rov'}, 400)
        p = urlparse(self.path).path
        with lock:
            if p == '/api/login':
                name = str(data.get('name', '')).strip()[:30]
                if len(name) < 2:
                    return self._json({'error': 'Ism kamida 2 harf bo‘lishi kerak'}, 400)
                t = data.get('team')
                if not (isinstance(t, int) and 0 <= t < len(state['teams'])):
                    t = None
                state['players'][name] = t
                return self._json({'ok': True})

            if p == '/api/answer':
                t, c = data.get('team'), data.get('choice')
                cur = state['cur']
                if cur is None or state['revealed']:
                    return self._json({'error': 'Hozir javob qabul qilinmaydi'}, 400)
                opts = state['shown_opts']
                if not opts:
                    return self._json({'error': 'Bu savolga og‘zaki javob beriladi'}, 400)
                if not (isinstance(t, int) and 0 <= t < len(state['teams'])) or not (isinstance(c, int) and 0 <= c < len(opts)):
                    return self._json({'error': 'Noto‘g‘ri ma‘lumot'}, 400)
                if t not in state['answers']:
                    state['answers'][t] = c
                return self._json({'ok': True})

            if p == '/api/admin':
                if data.get('pin') != PIN:
                    return self._json({'error': 'PIN noto‘g‘ri'}, 403)
                act = data.get('action')
                if act == 'open':
                    idx = data.get('idx')
                    if isinstance(idx, int) and 0 <= idx < len(QS):
                        q = QS[idx]
                        n = len(q['opts'])
                        perm = list(range(n))
                        random.shuffle(perm)
                        state['shown_opts'] = [q['opts'][i] for i in perm]
                        state['shown_c'] = perm.index(q['c']) if n else None
                        state.update(cur=idx, revealed=False, answers={})
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
                    state.update(cur=None, revealed=False, answers={})
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
                    state.update(scores=[0, 0, 0, 0], cur=None, revealed=False,
                                 used=[False] * len(QS), answers={})
                else:
                    return self._json({'error': 'Noma‘lum amal'}, 400)
                return self._json(public_state(admin=True))

        self._send(404, 'Topilmadi', 'text/plain; charset=utf-8')

if __name__ == '__main__':
    ip = local_ip()
    print('=' * 52)
    print(f'  Quiz fayli: {os.path.basename(QS_PATH)}  ({len(QS)} savol)')
    letters = ['A', 'B', 'C', 'D']
    print('  To‘g‘ri javoblar (fayl bo‘yicha): ' + '  '.join(f'{letters[k]}={_dist.get(k, 0)}' for k in range(4)))
    print('  STATISTIKA QUIZ server ishga tushdi')
    print(f'  O‘quvchilar uchun:  http://{ip}:{PORT}')
    print(f'  O‘qituvchi paneli:  http://{ip}:{PORT}/admin')
    print(f'  Admin PIN:          {PIN}')
    print('  To‘xtatish: Ctrl+C')
    print('=' * 52)
    try:
        srv = QuietServer(('0.0.0.0', PORT), H)
    except OSError:
        print()
        print(f'XATO: {PORT}-port band. Boshqa server hali ishlayapti.')
        print('Avval o‘sha serverni to‘xtating (Ctrl+C), keyin qayta ishga tushiring.')
        sys.exit(1)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
