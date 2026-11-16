"""JEO QUIZ + TEST X + MILLIONER + AUKSION + HUDUDLAR JANGI + ZANJIRLI BOMBA."""
import base64, collections, glob, io, json, os, random, re, socket, sys, threading, time, zipfile
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
API_BASE = 'https' + '://generativelanguage.googleapis.com/v1beta/models'

MIL_PRIZES = [100, 200, 300, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000, 125000, 250000, 500000, 1000000]
MIL_SAFE = {4: 1000, 9: 32000, 14: 1000000}

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
    'mode': 'jeopardy',
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
    'mil': None,
    'auc': None,
    'ter': None,
    'bomb': None,
    'kahoot': None,
}

def mc_indices():
    return [i for i, q in enumerate(QS) if len(q.get('opts') or []) >= 4]

def shuffled_opts(q_idx):
    q = QS[q_idx]
    opts = list(q.get('opts') or [])[:4]
    perm = list(range(len(opts)))
    random.shuffle(perm)
    return [opts[i] for i in perm], (perm.index(q['c']) if opts else 0)

# --- 1. KAHOOT! LUX LIVE ---
def start_kahoot_game(duration=20):
    order = mc_indices()
    random.shuffle(order)
    if not order:
        raise RuntimeError('Kahoot o‘yini uchun 4 variantli savollar topilmadi')
    dur = max(5, min(60, int(duration or 20)))
    state['mode'] = 'kahoot'
    state['kahoot'] = {
        'phase': 'lobby',
        'order': order,
        'q_num': 0,
        'total_q': len(order),
        'duration': dur,
        'q_start': 0.0,
        'shown_opts': [],
        'shown_c': 0,
        'round_answers': {},
        'scores': {
            nm: {'pts': 0, 'streak': 0, 'correct': 0, 'team': tm}
            for nm, tm in state['players'].items()
        },
        'team_pts': [0, 0, 0, 0],
    }

def finalize_kahoot_round(k):
    if not k or k['phase'] != 'question':
        return
    k['phase'] = 'reveal'
    correct_idx = k['shown_c']
    dur = max(1, k['duration'])
    for name, ans in k['round_answers'].items():
        if name not in k['scores']:
            k['scores'][name] = {'pts': 0, 'streak': 0, 'correct': 0, 'team': ans.get('team')}
        rec = k['scores'][name]
        if ans.get('team') is not None:
            rec['team'] = ans.get('team')
        if ans['choice'] == correct_idx:
            elapsed = min(dur, max(0.0, ans['ts'] - k['q_start']))
            speed_pts = round(1000 * (1.0 - (elapsed / dur) / 2.0))
            rec['streak'] += 1
            streak_bonus = min(500, (rec['streak'] - 1) * 100)
            gained = speed_pts + streak_bonus
            rec['pts'] += gained
            rec['correct'] += 1
            ans['gained'] = gained
            ans['ok'] = True
            t = rec.get('team')
            if isinstance(t, int) and 0 <= t < 4:
                k['team_pts'][t] += gained
        else:
            rec['streak'] = 0
            ans['gained'] = 0
            ans['ok'] = False

def serialize_kahoot(admin=False):
    k = state.get('kahoot')
    if not k:
        return None
    now = time.time()
    if k['phase'] == 'question':
        elapsed = now - k['q_start']
        rem = max(0.0, round(k['duration'] - elapsed, 1))
        total_players = len(state['players'])
        if rem <= 0 or (total_players > 0 and len(k['round_answers']) >= total_players):
            finalize_kahoot_round(k)
            rem = 0.0
    else:
        rem = 0.0

    counts = [0, 0, 0, 0]
    for ans in k['round_answers'].values():
        ch = ans.get('choice')
        if ch in (0, 1, 2, 3):
            counts[ch] += 1

    leaderboard = sorted(
        [{'name': nm, **info} for nm, info in k['scores'].items()],
        key=lambda x: (-x['pts'], -x['correct'], x['name'])
    )

    q_out = None
    if k['phase'] in ('question', 'reveal') and k['q_num'] < len(k['order']):
        q = QS[k['order'][k['q_num']]]
        q_out = {
            'cat': q['cat'],
            'q': q['q'],
            'opts': list(k['shown_opts']),
        }
        if k['phase'] in ('reveal', 'podium') or admin:
            q_out['c'] = k['shown_c']
            q_out['exp'] = q.get('exp', '')

    return {
        'phase': k['phase'],
        'q_num': k['q_num'],
        'total_q': k['total_q'],
        'duration': k['duration'],
        'time_left': rem,
        'question': q_out,
        'answered_count': len(k['round_answers']),
        'answered_names': list(k['round_answers'].keys()),
        'vote_counts': counts,
        'round_results': k['round_answers'] if k['phase'] in ('reveal', 'podium') else {},
        'leaderboard': leaderboard,
        'team_pts': list(k['team_pts']),
    }

# --- 2. MILLIONAIRE ---
def build_millionaire_ladder():
    by_pts = collections.defaultdict(list)
    all_mc = mc_indices()
    for i in all_mc:
        by_pts[QS[i].get('pts', 100)].append(i)
    ladder = []
    for pts in (100, 200, 300, 400, 500):
        pool = list(by_pts.get(pts, []))
        random.shuffle(pool)
        ladder.extend(pool[:3])
    if len(ladder) < 15:
        rest = [i for i in all_mc if i not in ladder]
        random.shuffle(rest)
        ladder.extend(rest[:15 - len(ladder)])
    return ladder[:15]

def prepare_mil_step(mil, step_idx):
    shown_opts, shown_c = shuffled_opts(mil['ladder'][step_idx])
    mil['step'] = step_idx
    mil['shown_opts'] = shown_opts
    mil['shown_c'] = shown_c
    mil['hidden_opts'] = []
    mil['selected'] = None
    mil['revealed'] = False
    mil['audience_open'] = False
    mil['votes'] = {}
    mil['ai_hint'] = ''

def start_millionaire_run(player_name='Ishtirokchi', team_idx=None):
    ladder = build_millionaire_ladder()
    if not ladder:
        raise RuntimeError('Millioner o‘yini uchun 4 variantli savollar topilmadi')
    mil = {
        'active': True,
        'status': 'playing',
        'player': (player_name or 'Ishtirokchi').strip()[:30] or 'Ishtirokchi',
        'team': team_idx if (isinstance(team_idx, int) and 0 <= team_idx < 4) else None,
        'ladder': ladder,
        'step': 0,
        'won': 0,
        'lifelines': {'fifty': True, 'audience': True, 'ai': True},
        'hidden_opts': [],
        'selected': None,
        'revealed': False,
        'audience_open': False,
        'votes': {},
        'ai_hint': '',
        'shown_opts': [],
        'shown_c': 0,
        'credited': False,
    }
    prepare_mil_step(mil, 0)
    state['mil'] = mil

def apply_mil_action(act, data):
    mil = state.get('mil')
    if act == 'select':
        c = data.get('choice')
        if not mil or not mil['active'] or mil['revealed']:
            return 'Hozir variant tanlab bo‘lmaydi'
        if not (isinstance(c, int) and 0 <= c < 4) or c in mil['hidden_opts']:
            return 'Noto‘g‘ri variant'
        mil['selected'] = c
        return None
    if act == 'reveal':
        if not mil or not mil['active'] or mil['revealed']:
            return 'Tekshirish uchun faol savol yo‘q'
        if mil['selected'] is None:
            return 'Avval variantni tanlang'
        mil['revealed'] = True
        mil['audience_open'] = False
        step = mil['step']
        if mil['selected'] == mil['shown_c']:
            mil['won'] = MIL_PRIZES[step]
            if step >= len(mil['ladder']) - 1:
                mil['status'] = 'won'
                mil['active'] = False
        else:
            safe_won = 0
            for s_idx, s_val in MIL_SAFE.items():
                if step > s_idx:
                    safe_won = s_val
            mil['won'] = safe_won
            mil['status'] = 'lost'
            mil['active'] = False
        return None
    if act == 'next':
        if not mil or not mil['revealed'] or mil['status'] != 'playing':
            return 'Keyingi savolga o‘tib bo‘lmaydi'
        if mil['step'] + 1 >= len(mil['ladder']):
            mil['status'] = 'won'
            mil['active'] = False
        else:
            prepare_mil_step(mil, mil['step'] + 1)
        return None
    if act == 'walk':
        if not mil or not mil['active']:
            return 'Faol o‘yin yo‘q'
        mil['status'] = 'walked'
        mil['active'] = False
        mil['audience_open'] = False
        return None
    if act == '5050':
        if not mil or not mil['active'] or mil['revealed']:
            return 'Hozir 50:50 ishlatib bo‘lmaydi'
        if not mil['lifelines'].get('fifty'):
            return '50:50 allaqachon ishlatilgan'
        wrongs = [i for i in range(4) if i != mil['shown_c']]
        random.shuffle(wrongs)
        mil['hidden_opts'] = sorted(wrongs[:2])
        if mil['selected'] in mil['hidden_opts']:
            mil['selected'] = None
        mil['lifelines']['fifty'] = False
        return None
    if act == 'audience':
        if not mil or not mil['active'] or mil['revealed']:
            return 'Hozir guruh yordami ishlatib bo‘lmaydi'
        if not mil['lifelines'].get('audience'):
            return 'Guruh yordami allaqachon ishlatilgan'
        mil['lifelines']['audience'] = False
        mil['audience_open'] = True
        mil['votes'] = {}
        return None
    return 'Noma‘lum amal'

# --- 3. AUKSION VA STAVKA ---
def start_auction_game():
    order = mc_indices()
    random.shuffle(order)
    if not order:
        raise RuntimeError('Auksion o‘yini uchun 4 variantli savollar topilmadi')
    auc = {
        'bank': [1000, 1000, 1000, 1000],
        'order': order,
        'idx': 0,
        'phase': 'betting',
        'bets': {},
        'answers': {},
        'shown_opts': [],
        'shown_c': 0,
        'deltas': [0, 0, 0, 0],
    }
    shown_opts, shown_c = shuffled_opts(order[0])
    auc['shown_opts'] = shown_opts
    auc['shown_c'] = shown_c
    state['auc'] = auc

def serialize_auc(admin=False):
    auc = state.get('auc')
    if not auc:
        return None
    q_idx = auc['order'][auc['idx']]
    q = QS[q_idx]
    out = {
        'bank': list(auc['bank']),
        'round': auc['idx'] + 1,
        'total_rounds': len(auc['order']),
        'phase': auc['phase'],
        'bets': {str(k): v for k, v in auc['bets'].items()},
        'answered_teams': sorted(list(auc['answers'].keys())),
        'deltas': list(auc['deltas']),
        'cat': q['cat'],
        'pts': q['pts'],
    }
    if auc['phase'] in ('question', 'revealed') or admin:
        out['question'] = {
            'q': q['q'],
            'opts': list(auc['shown_opts']),
        }
        if auc['phase'] == 'revealed' or admin:
            out['question']['c'] = auc['shown_c']
            out['question']['exp'] = q.get('exp', '')
            out['answers'] = {str(k): v for k, v in auc['answers'].items()}
    return out

# --- 4. HUDUDLAR JANGI (5x5 XARITA) ---
def start_territory_game():
    state['ter'] = {
        'owners': [None] * 25,
        'cur_cell': None,
        'phase': 'pick',
        'shown_opts': [],
        'shown_c': 0,
        'winner': None,
        'wrong_teams': [],
        'last_msg': 'Xaritadan biror katakchani tanlang',
    }

def serialize_ter(admin=False):
    ter = state.get('ter')
    if not ter:
        return None
    counts = [sum(1 for o in ter['owners'] if o == t) for t in range(4)]
    out = {
        'owners': list(ter['owners']),
        'counts': counts,
        'cur_cell': ter['cur_cell'],
        'phase': ter['phase'],
        'winner': ter['winner'],
        'wrong_teams': list(ter['wrong_teams']),
        'last_msg': ter['last_msg'],
    }
    if ter['cur_cell'] is not None:
        q = QS[ter['cur_cell']]
        qq = {'cat': q['cat'], 'pts': q['pts'], 'q': q['q'], 'opts': list(ter['shown_opts'])}
        if ter['phase'] == 'revealed' or admin:
            qq['c'] = ter['shown_c']
            qq['exp'] = q.get('exp', '')
        out['question'] = qq
    return out

# --- 5. ZANJIRLI BOMBA ---
def start_bomb_game(start_sec=20):
    order = mc_indices()
    random.shuffle(order)
    if not order:
        raise RuntimeError('Bomba o‘yini uchun 4 variantli savollar topilmadi')
    shown_opts, shown_c = shuffled_opts(order[0])
    sec = max(8, min(40, int(start_sec or 20)))
    state['bomb'] = {
        'lives': [3, 3, 3, 3],
        'holder': 0,
        'order': order,
        'idx': 0,
        'base_sec': sec,
        'cur_sec': sec,
        'deadline': time.time() + sec,
        'status': 'playing',
        'shown_opts': shown_opts,
        'shown_c': shown_c,
        'last_choice': None,
        'last_msg': 'Bomba 1-jamoaning qo‘lida!',
    }

def next_alive_team(lives, current):
    for step in range(1, 5):
        cand = (current + step) % 4
        if lives[cand] > 0:
            return cand
    return current

def check_bomb_timeout():
    bomb = state.get('bomb')
    if not bomb or bomb['status'] != 'playing':
        return
    if time.time() >= bomb['deadline']:
        h = bomb['holder']
        bomb['lives'][h] = max(0, bomb['lives'][h] - 1)
        alive = [i for i, lv in enumerate(bomb['lives']) if lv > 0]
        if len(alive) <= 1:
            bomb['status'] = 'gameover'
            win_t = alive[0] if alive else h
            bomb['last_msg'] = f'VAQT TUGADI! 💥 Oxirgi omon qolgan g‘olib: {state["teams"][win_t]}!'
        else:
            bomb['status'] = 'boom'
            bomb['last_msg'] = f'VAQT TUGADI! 💥 {state["teams"][h]} 1 ta jon yo‘qotdi!'

def serialize_bomb(admin=False):
    check_bomb_timeout()
    bomb = state.get('bomb')
    if not bomb:
        return None
    q = QS[bomb['order'][bomb['idx'] % len(bomb['order'])]]
    left = max(0.0, round(bomb['deadline'] - time.time(), 1)) if bomb['status'] == 'playing' else 0.0
    out = {
        'lives': list(bomb['lives']),
        'holder': bomb['holder'],
        'cur_sec': bomb['cur_sec'],
        'time_left': left,
        'status': bomb['status'],
        'last_choice': bomb['last_choice'],
        'last_msg': bomb['last_msg'],
        'question': {
            'cat': q['cat'],
            'q': q['q'],
            'opts': list(bomb['shown_opts']),
        }
    }
    if bomb['status'] in ('boom', 'gameover') or admin:
        out['question']['c'] = bomb['shown_c']
        out['question']['exp'] = q.get('exp', '')
    return out

# --- GEMINI AI HELPERS ---
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

def extract_docx_text(raw_bytes):
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        xml_bytes = zf.read('word/document.xml')
    root = ET.fromstring(xml_bytes)
    lines = []
    for p in root.iter():
        if p.tag.endswith('}p'):
            parts = [t.text for t in p.iter() if t.tag.endswith('}t') and t.text]
            if parts:
                lines.append(''.join(parts))
    return '\n'.join(lines)

def decode_text_bytes(raw_bytes):
    for enc in ('utf-8', 'utf-8-sig', 'cp1251', 'latin-1'):
        try:
            return raw_bytes.decode(enc)
        except Exception:
            continue
    return raw_bytes.decode('utf-8', errors='ignore')

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

def call_gemini(prompt, json_mode=False, temperature=0.6, file_part=None):
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
            if file_part and m.startswith('gemma'):
                continue
            candidates.append(m)

    parts = []
    if file_part:
        parts.append({'inlineData': {'mimeType': file_part['mime_type'], 'data': file_part['data']}})
    parts.append({'text': prompt})

    raw = None
    real_err = None
    fallback_err = 'AI javob bermadi'

    def try_models(model_list):
        nonlocal raw, real_err, fallback_err
        for model in model_list:
            if file_part and model.startswith('gemma'):
                continue
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
                    'contents': [{'parts': parts}],
                    'generationConfig': gen_cfg
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode('utf8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                try:
                    with urllib.request.urlopen(req, timeout=65) as resp:
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

def parse_category_items(data, cname):
    qs_list = data.get('s') or data.get('questions') or []
    if len(qs_list) != 5:
        return None
    cat_qs = []
    for idx, item in enumerate(qs_list):
        opts = [str(x).strip() for x in (item.get('o') or item.get('opts') or [])][:4]
        if len(opts) < 4:
            return None
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
    return cat_qs

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
            cat_qs = parse_category_items(data, cname)
            if cat_qs:
                return cat_qs
            last_e = RuntimeError(f'"{cname}" bo‘limida 5 ta savol chiqmadi')
        except Exception as e:
            last_e = e
            time.sleep(0.5)
    raise RuntimeError(f'"{cname}" bo‘limida xato: {last_e}')

def ai_generate_category_from_source(cname, level, hint, doc_text='', file_part=None):
    source_block = f'\nHUJJAT MATNI:\n"""\n{doc_text}\n"""\n' if doc_text else ''
    hint_line = f'Qo‘shimcha ko‘rsatma: {hint}.' if hint else ''
    prompt = f"""Yuklangan hujjat asosida o‘zbek tilida "{cname}" bo‘limi uchun ({level}) 5 ta test savoli tayyorla (100, 200, 300, 400, 500 ball).
{hint_line}
Muhim:
- Agar hujjatda tayyor test savollari va javoblari berilgan bo‘lsa, shu bo‘limga mos 5 ta savol-javobni ajratib ol va 4 ta variantli test ko‘rinishiga keltir (to‘g‘ri javobini aniq saqla).
- Agar hujjat ma’ruza matni yoki nazariy material bo‘lsa, faqat shu hujjatdagi faktlar asosida 5 ta savol tuz.
- Savol, variant va izoh ichida qo‘shtirnoq (") belgisini umuman ishlatma (kerak bo‘lsa « » ishlat).
{source_block}
FAQAT shu JSON formatida qaytar:
{{"s":[{{"q":"Savol matni","o":["A","B","C","D"],"c":0,"e":"1 gap izoh"}}]}}"""
    last_e = None
    for _ in range(3):
        try:
            data = call_gemini(prompt, json_mode=True, temperature=0.45, file_part=file_part)
            cat_qs = parse_category_items(data, cname)
            if cat_qs:
                return cat_qs
            last_e = RuntimeError(f'"{cname}" bo‘limida 5 ta savol chiqmadi')
        except Exception as e:
            last_e = e
            time.sleep(0.5)
    raise RuntimeError(f'"{cname}" bo‘limida xato: {last_e}')

def refresh_active_mode_after_new_qs():
    m = state['mode']
    if m == 'kahoot':
        start_kahoot_game(20)
    elif m == 'millionaire':
        start_millionaire_run('Ishtirokchi', None)
    elif m == 'auction':
        start_auction_game()
    elif m == 'territory':
        start_territory_game()
    elif m == 'bomb':
        start_bomb_game(20)

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
            refresh_active_mode_after_new_qs()
    except Exception as e:
        with lock:
            state['ai_busy'] = False
            state['ai_status'] = ''
            state['ai_error'] = str(e)

def bg_generate_from_file(filename, mime, b64_data, hint, level):
    global QS, _cats
    try:
        with lock:
            state['ai_status'] = f'"{filename}" fayli o‘qilmoqda...'
        raw_bytes = base64.b64decode(b64_data)
        fname_low = filename.lower()
        doc_text = ''
        file_part = None

        if fname_low.endswith('.docx') or 'wordprocessingml' in mime:
            doc_text = extract_docx_text(raw_bytes).strip()
            if len(doc_text) < 30:
                raise RuntimeError('Word (.docx) fayl ichidan yetarli matn topilmadi')
            doc_text = doc_text[:45000]
        elif fname_low.endswith(('.txt', '.md', '.csv')) or mime.startswith('text/'):
            doc_text = decode_text_bytes(raw_bytes).strip()
            if len(doc_text) < 30:
                raise RuntimeError('Matnli fayl bo‘sh yoki juda qisqa')
            doc_text = doc_text[:45000]
        elif fname_low.endswith('.doc'):
            raise RuntimeError('Eski .doc formati qo‘llab-quvvatlanmaydi. Faylni .docx yoki .pdf qilib saqlab yuklang.')
        else:
            if not mime:
                if fname_low.endswith('.pdf'):
                    mime = 'application/pdf'
                elif fname_low.endswith('.png'):
                    mime = 'image/png'
                else:
                    mime = 'image/jpeg'
            file_part = {'mime_type': mime, 'data': b64_data}

        with lock:
            state['ai_status'] = 'Fayl tahlil qilinmoqda, 5 ta bo‘lim ajratilmoqda...'

        source_block = f'\nHUJJAT MATNI:\n"""\n{doc_text}\n"""\n' if doc_text else ''
        cat_prompt = f"""Yuklangan hujjatni tahlil qil va undagi mavzular asosida o‘zbek tilida 5 ta alohida bo‘lim nomini tuz ({level}).
Qo‘shimcha ko‘rsatma: "{hint or 'hujjat mazmunini to‘liq qamrab ol'}".
Matn ichida qo‘shtirnoq (") ishlatma.
{source_block}
FAQAT shu JSONni qaytar: {{"categories":["1-bo‘lim","2-bo‘lim","3-bo‘lim","4-bo‘lim","5-bo‘lim"]}}"""

        cat_data = call_gemini(cat_prompt, json_mode=True, temperature=0.45, file_part=file_part)
        raw_cats = [str(x).strip()[:35] for x in (cat_data.get('categories') or []) if str(x).strip()]
        cats = []
        for c in raw_cats:
            if c not in cats:
                cats.append(c)
        if len(cats) < 5:
            raise RuntimeError('Fayldan 5 ta bo‘lim ajratib bo‘lmadi, qayta urinib ko‘ring')
        cats = cats[:5]

        result = []
        for i, cname in enumerate(cats):
            with lock:
                state['ai_status'] = f'{i+1}/5-bo‘lim savollari tuzilmoqda: {cname}...'
            cat_qs = ai_generate_category_from_source(cname, level, hint, doc_text=doc_text, file_part=file_part)
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
                ai_status=f'Tayyor! "{filename}" faylidan 25 ta savol-javob jadvalga yuklandi ✔'
            )
            refresh_active_mode_after_new_qs()
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

def ai_millionaire_hint(q_text, opts, hidden_opts, correct_idx):
    letters = ['A', 'B', 'C', 'D']
    visible = [f'{letters[i]}) {opts[i]}' for i in range(len(opts)) if i not in hidden_opts]
    ans = opts[correct_idx]
    prompt = f"""«Kim millioner bo‘lishni xohlaydi?» o‘yinida aqlli yordamchi sifatida o‘zbek tilida 2 gaplik maslahat ber.
Savol: {q_text}
Variantlar: {' | '.join(visible)}
To‘g‘ri javob: {ans}
Qoidalar: Ishtirokchini to‘g‘ri javob tomon mantiqiy yo‘naltir va oxirida qaysi variant ehtimoli yuqori ekanini ayt."""
    return call_gemini(prompt, json_mode=False, temperature=0.5)

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

def serialize_mil(admin=False):
    mil = state.get('mil')
    if not mil:
        return None
    q = QS[mil['ladder'][mil['step']]]
    vote_counts = [0, 0, 0, 0]
    for v in mil['votes'].values():
        if isinstance(v, int) and 0 <= v < 4:
            vote_counts[v] += 1
    out = {
        'active': mil['active'],
        'status': mil['status'],
        'player': mil['player'],
        'team': mil['team'],
        'step': mil['step'],
        'total_steps': len(mil['ladder']),
        'prizes': MIL_PRIZES[:len(mil['ladder'])],
        'safe_steps': sorted(list(MIL_SAFE.keys())),
        'won': mil['won'],
        'lifelines': dict(mil['lifelines']),
        'hidden_opts': list(mil['hidden_opts']),
        'selected': mil['selected'],
        'revealed': mil['revealed'],
        'audience_open': mil['audience_open'],
        'vote_counts': vote_counts,
        'vote_total': sum(vote_counts),
        'ai_hint': mil['ai_hint'],
        'credited': mil['credited'],
        'question': {
            'cat': q['cat'],
            'q': q['q'],
            'opts': list(mil['shown_opts']),
        }
    }
    if mil['revealed'] or admin:
        out['question']['c'] = mil['shown_c']
        out['question']['exp'] = q.get('exp', '')
    return out

def public_state(admin=False):
    s = {
        'mode': state['mode'],
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
    if state['mode'] == 'kahoot' or admin:
        s['kahoot'] = serialize_kahoot(admin=admin)
    if state['mode'] == 'millionaire' or admin:
        s['mil'] = serialize_mil(admin=admin)
    if state['mode'] == 'auction' or admin:
        s['auc'] = serialize_auc(admin=admin)
    if state['mode'] == 'territory' or admin:
        s['ter'] = serialize_ter(admin=admin)
    if state['mode'] == 'bomb' or admin:
        s['bomb'] = serialize_bomb(admin=admin)
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
        if n > 16 * 1024 * 1024:
            return self._json({'error': 'Fayl hajmi juda katta (maksimum 10 MB)'}, 413)
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
                k = state.get('kahoot')
                if k is not None:
                    if name not in k['scores']:
                        k['scores'][name] = {'pts': 0, 'streak': 0, 'correct': 0, 'team': t}
                    else:
                        k['scores'][name]['team'] = t
                return self._json({'ok': True})

        if p == '/api/kahoot_play':
            with lock:
                k = state.get('kahoot')
                if state['mode'] != 'kahoot' or not k or k['phase'] != 'question':
                    return self._json({'error': 'Hozir javob qabul qilinmayapti'}, 400)
                if time.time() - k['q_start'] > k['duration']:
                    finalize_kahoot_round(k)
                    return self._json({'error': 'Vaqt tugadi!'}, 400)
                name = str(data.get('name', '')).strip()[:30] or 'Ishtirokchi'
                t = data.get('team')
                if not (isinstance(t, int) and 0 <= t < 4):
                    t = state['players'].get(name)
                choice = data.get('choice')
                if not (isinstance(choice, int) and 0 <= choice < 4):
                    return self._json({'error': 'Noto‘g‘ri variant'}, 400)
                if name not in k['round_answers']:
                    k['round_answers'][name] = {'choice': choice, 'ts': time.time(), 'team': t}
                if name not in k['scores']:
                    k['scores'][name] = {'pts': 0, 'streak': 0, 'correct': 0, 'team': t}
                if len(state['players']) > 0 and len(k['round_answers']) >= len(state['players']):
                    finalize_kahoot_round(k)
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

        if p == '/api/mil_vote':
            with lock:
                mil = state.get('mil')
                if state['mode'] != 'millionaire' or not mil or not mil['audience_open'] or mil['revealed']:
                    return self._json({'error': 'Hozir guruh ovozi ochiq emas'}, 400)
                voter = str(data.get('voter', '')).strip()[:40] or 'mehmon'
                c = data.get('choice')
                if not (isinstance(c, int) and 0 <= c < 4) or c in mil['hidden_opts']:
                    return self._json({'error': 'Noto‘g‘ri variant'}, 400)
                mil['votes'][voter] = c
                return self._json({'ok': True})

        if p == '/api/mil_play':
            act = data.get('action')
            if state['mode'] != 'millionaire':
                return self._json({'error': 'Millioner rejimi faol emas'}, 400)
            if act == 'ai':
                with lock:
                    mil = state.get('mil')
                    if not mil or not mil['active'] or mil['revealed']:
                        return self._json({'error': 'Hozir AI yordami mumkin emas'}, 400)
                    if not mil['lifelines'].get('ai'):
                        return self._json({'error': 'Gemini AI yordami allaqachon ishlatilgan'}, 400)
                    q_obj = QS[mil['ladder'][mil['step']]]
                    q_text = q_obj['q']
                    opts_copy = list(mil['shown_opts'])
                    hidden_copy = list(mil['hidden_opts'])
                    c_copy = mil['shown_c']
                try:
                    hint_txt = ai_millionaire_hint(q_text, opts_copy, hidden_copy, c_copy)
                except Exception as e:
                    return self._json({'error': str(e)}, 500)
                with lock:
                    mil = state.get('mil')
                    if mil:
                        mil['lifelines']['ai'] = False
                        mil['ai_hint'] = hint_txt
                return self._json({'ok': True})
            with lock:
                err = apply_mil_action(act, data)
                if err:
                    return self._json({'error': err}, 400)
                return self._json({'ok': True})

        # --- STUDENT API: AUCTION ---
        if p == '/api/auc_play':
            with lock:
                auc = state.get('auc')
                if state['mode'] != 'auction' or not auc:
                    return self._json({'error': 'Auksion rejimi faol emas'}, 400)
                t = data.get('team')
                if not (isinstance(t, int) and 0 <= t < 4):
                    return self._json({'error': 'Avval jamoangizni tanlang'}, 400)
                act = data.get('action')
                if act == 'bet':
                    if auc['phase'] != 'betting':
                        return self._json({'error': 'Stavka vaqti tugagan'}, 400)
                    amt = int(data.get('amount') or 0)
                    cap = max(100, auc['bank'][t])
                    if amt < 50 or amt > cap:
                        return self._json({'error': f'Stavka 50 dan {cap} gacha bo‘lishi kerak'}, 400)
                    auc['bets'][t] = amt
                    return self._json({'ok': True})
                if act == 'answer':
                    if auc['phase'] != 'question':
                        return self._json({'error': 'Hozir javob berish vaqti emas'}, 400)
                    c = data.get('choice')
                    if not (isinstance(c, int) and 0 <= c < 4):
                        return self._json({'error': 'Noto‘g‘ri variant'}, 400)
                    if t not in auc['answers']:
                        auc['answers'][t] = c
                    return self._json({'ok': True})
                return self._json({'error': 'Noma‘lum amal'}, 400)

        # --- STUDENT API: TERRITORY ---
        if p == '/api/ter_play':
            with lock:
                ter = state.get('ter')
                if state['mode'] != 'territory' or not ter:
                    return self._json({'error': 'Hududlar jangi faol emas'}, 400)
                t = data.get('team')
                if not (isinstance(t, int) and 0 <= t < 4):
                    return self._json({'error': 'Avval jamoangizni tanlang'}, 400)
                if ter['phase'] != 'battle' or ter['cur_cell'] is None:
                    return self._json({'error': 'Hozir jang ketmayapti'}, 400)
                if t in ter['wrong_teams']:
                    return self._json({'error': 'Sizning jamoangiz bu katakda xato javob berdi'}, 400)
                c = data.get('choice')
                if not (isinstance(c, int) and 0 <= c < 4):
                    return self._json({'error': 'Noto‘g‘ri variant'}, 400)
                if c == ter['shown_c']:
                    cell = ter['cur_cell']
                    prev_owner = ter['owners'][cell]
                    ter['owners'][cell] = t
                    ter['winner'] = t
                    ter['phase'] = 'revealed'
                    if prev_owner is not None and prev_owner != t:
                        ter['last_msg'] = f'{state["teams"][t]} ({cell+1}-sektor)ni {state["teams"][prev_owner]}dan tortib oldi!'
                    else:
                        ter['last_msg'] = f'{state["teams"][t]} ({cell+1}-sektor)ni egalladi!'
                else:
                    ter['wrong_teams'].append(t)
                    if len(ter['wrong_teams']) >= 4:
                        ter['phase'] = 'revealed'
                        ter['last_msg'] = 'Barcha jamoalar xato javob berdi — sektor egasiz qoldi!'
                return self._json({'ok': True})

        # --- STUDENT API: BOMB ---
        if p == '/api/bomb_play':
            with lock:
                check_bomb_timeout()
                bomb = state.get('bomb')
                if state['mode'] != 'bomb' or not bomb or bomb['status'] != 'playing':
                    return self._json({'error': 'Bomba hozir faol emas'}, 400)
                t = data.get('team')
                if t != bomb['holder']:
                    return self._json({'error': 'Bomba hozir sizning jamoangizda emas!'}, 400)
                c = data.get('choice')
                if not (isinstance(c, int) and 0 <= c < 4):
                    return self._json({'error': 'Noto‘g‘ri variant'}, 400)
                bomb['last_choice'] = c
                if c == bomb['shown_c']:
                    nxt = next_alive_team(bomb['lives'], t)
                    bomb['holder'] = nxt
                    bomb['idx'] += 1
                    bomb['cur_sec'] = max(8, bomb['cur_sec'] - 2)
                    bomb['deadline'] = time.time() + bomb['cur_sec']
                    bomb['last_choice'] = None
                    q_idx = bomb['order'][bomb['idx'] % len(bomb['order'])]
                    shown_opts, shown_c = shuffled_opts(q_idx)
                    bomb['shown_opts'] = shown_opts
                    bomb['shown_c'] = shown_c
                    bomb['last_msg'] = f'To‘g‘ri! Bomba {state["teams"][nxt]}ga o‘tdi ({bomb["cur_sec"]}s)!'
                else:
                    bomb['lives'][t] = max(0, bomb['lives'][t] - 1)
                    alive = [i for i, lv in enumerate(bomb['lives']) if lv > 0]
                    if len(alive) <= 1:
                        bomb['status'] = 'gameover'
                        win_t = alive[0] if alive else t
                        bomb['last_msg'] = f'XATO! 💥 Oxirgi omon qolgan g‘olib: {state["teams"][win_t]}!'
                    else:
                        bomb['status'] = 'boom'
                        bomb['last_msg'] = f'XATO JAVOB! 💥 {state["teams"][t]} 1 ta jon yo‘qotdi!'
                return self._json({'ok': True})

        # --- ADMIN API ---
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

            if act == 'ai_generate_from_file':
                filename = str(data.get('filename', 'hujjat')).strip()
                mime = str(data.get('mime', '')).strip()
                b64_data = str(data.get('data_b64', '')).strip()
                hint = str(data.get('hint', '')).strip()
                level = str(data.get('level', 'universitet talabalari')).strip()
                if not b64_data:
                    return self._json({'error': 'Avval faylni tanlang'}, 400)
                with lock:
                    if state['ai_busy']:
                        return self._json({'error': 'AI hozir savol tuzmoqda, biroz kuting'}, 400)
                    state['ai_busy'] = True
                    state['ai_error'] = ''
                    state['ai_status'] = f'"{filename}" yuklanmoqda...'
                threading.Thread(
                    target=bg_generate_from_file,
                    args=(filename, mime, b64_data, hint, level),
                    daemon=True
                ).start()
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

            if act == 'mil_ai':
                with lock:
                    mil = state.get('mil')
                    if not mil or not mil['active'] or mil['revealed']:
                        return self._json({'error': 'Hozir AI yordami mumkin emas'}, 400)
                    if not mil['lifelines'].get('ai'):
                        return self._json({'error': 'Gemini AI yordami allaqachon ishlatilgan'}, 400)
                    q_obj = QS[mil['ladder'][mil['step']]]
                    q_text = q_obj['q']
                    opts_copy = list(mil['shown_opts'])
                    hidden_copy = list(mil['hidden_opts'])
                    c_copy = mil['shown_c']
                try:
                    hint_txt = ai_millionaire_hint(q_text, opts_copy, hidden_copy, c_copy)
                except Exception as e:
                    return self._json({'error': str(e)}, 500)
                with lock:
                    mil = state.get('mil')
                    if mil:
                        mil['lifelines']['ai'] = False
                        mil['ai_hint'] = hint_txt
                    return self._json(public_state(admin=True))

            with lock:
                if act == 'set_mode':
                    m = data.get('mode')
                    if m not in ('jeopardy', 'kahoot', 'millionaire', 'auction', 'territory', 'bomb'):
                        return self._json({'error': 'Noto‘g‘ri rejim'}, 400)
                    state['mode'] = m
                    try:
                        if m == 'millionaire' and not state.get('mil'):
                            start_millionaire_run('Ishtirokchi', None)
                        elif m == 'auction' and not state.get('auc'):
                            start_auction_game()
                        elif m == 'territory' and not state.get('ter'):
                            start_territory_game()
                        elif m == 'bomb' and not state.get('bomb'):
                            start_bomb_game(20)
                    except Exception as e:
                        return self._json({'error': str(e)}, 400)

                # --- KAHOOT ADMIN ---
                elif act == 'kahoot_start':
                    dur = data.get('duration', 20)
                    try:
                        start_kahoot_game(dur)
                    except Exception as e:
                        return self._json({'error': str(e)}, 400)
                elif act == 'kahoot_next':
                    k = state.get('kahoot')
                    if not k:
                        return self._json({'error': 'Avval Kahoot xonasini oching'}, 400)
                    if k['phase'] == 'question':
                        finalize_kahoot_round(k)
                    if k['phase'] != 'lobby':
                        k['q_num'] += 1
                    if k['q_num'] >= k['total_q']:
                        k['phase'] = 'podium'
                    else:
                        q_idx = k['order'][k['q_num']]
                        shown_opts, shown_c = shuffled_opts(q_idx)
                        k['shown_opts'] = shown_opts
                        k['shown_c'] = shown_c
                        k['round_answers'] = {}
                        k['q_start'] = time.time()
                        k['phase'] = 'question'
                elif act == 'kahoot_reveal':
                    k = state.get('kahoot')
                    if k and k['phase'] == 'question':
                        finalize_kahoot_round(k)
                elif act == 'kahoot_podium':
                    k = state.get('kahoot')
                    if k:
                        if k['phase'] == 'question':
                            finalize_kahoot_round(k)
                        k['phase'] = 'podium'
                elif act == 'kahoot_sync_scores':
                    k = state.get('kahoot')
                    if k:
                        for i in range(4):
                            state['scores'][i] += k['team_pts'][i]
                        k['team_pts'] = [0, 0, 0, 0]

                # --- MIL ADMIN ---
                elif act == 'mil_start':
                    player = str(data.get('player', '')).strip()
                    team = data.get('team')
                    if isinstance(team, str) and team.isdigit():
                        team = int(team)
                    elif not isinstance(team, int):
                        team = None
                    if not player and isinstance(team, int) and 0 <= team < 4:
                        player = state['teams'][team]
                    try:
                        start_millionaire_run(player or 'Ishtirokchi', team)
                    except Exception as e:
                        return self._json({'error': str(e)}, 400)
                elif act in ('mil_select', 'mil_reveal', 'mil_next', 'mil_walk', 'mil_5050', 'mil_audience'):
                    err = apply_mil_action(act.replace('mil_', ''), data)
                    if err:
                        return self._json({'error': err}, 400)
                elif act == 'mil_credit':
                    mil = state.get('mil')
                    if not mil or mil['credited'] or mil['won'] <= 0:
                        return self._json({'error': 'Qo‘shish uchun yutuq yo‘q yoki allaqachon qo‘shilgan'}, 400)
                    t = mil.get('team')
                    if not (isinstance(t, int) and 0 <= t < 4):
                        return self._json({'error': 'O‘yin boshida jamoa tanlanmagan'}, 400)
                    state['scores'][t] += mil['won']
                    mil['credited'] = True

                # --- AUCTION ADMIN ---
                elif act == 'auc_start':
                    try:
                        start_auction_game()
                    except Exception as e:
                        return self._json({'error': str(e)}, 400)
                elif act == 'auc_open_q':
                    auc = state.get('auc')
                    if not auc or auc['phase'] != 'betting':
                        return self._json({'error': 'Avval stavka bosqichi bo‘lishi kerak'}, 400)
                    for t in range(4):
                        if t not in auc['bets']:
                            auc['bets'][t] = min(100, max(50, auc['bank'][t]))
                    auc['phase'] = 'question'
                elif act == 'auc_reveal':
                    auc = state.get('auc')
                    if not auc or auc['phase'] != 'question':
                        return self._json({'error': 'Savol ochiq emas'}, 400)
                    deltas = [0, 0, 0, 0]
                    for t in range(4):
                        bet = auc['bets'].get(t, 0)
                        ans = auc['answers'].get(t)
                        if ans == auc['shown_c']:
                            auc['bank'][t] += bet
                            deltas[t] = bet
                        else:
                            auc['bank'][t] = max(100, auc['bank'][t] - bet)
                            deltas[t] = -bet
                    auc['deltas'] = deltas
                    auc['phase'] = 'revealed'
                elif act == 'auc_next':
                    auc = state.get('auc')
                    if not auc:
                        return self._json({'error': 'Auksion boshlanmagan'}, 400)
                    auc['idx'] = (auc['idx'] + 1) % len(auc['order'])
                    auc['phase'] = 'betting'
                    auc['bets'] = {}
                    auc['answers'] = {}
                    auc['deltas'] = [0, 0, 0, 0]
                    shown_opts, shown_c = shuffled_opts(auc['order'][auc['idx']])
                    auc['shown_opts'] = shown_opts
                    auc['shown_c'] = shown_c
                elif act == 'auc_sync_scores':
                    auc = state.get('auc')
                    if auc:
                        for t in range(4):
                            state['scores'][t] += auc['bank'][t]

                # --- TERRITORY ADMIN ---
                elif act == 'ter_start':
                    start_territory_game()
                elif act == 'ter_pick':
                    ter = state.get('ter')
                    idx = data.get('idx')
                    if not ter or not (isinstance(idx, int) and 0 <= idx < 25):
                        return self._json({'error': 'Noto‘g‘ri katakcha'}, 400)
                    if len(QS[idx].get('opts') or []) < 4:
                        return self._json({'error': 'Bu katakda 4 variantli savol yo‘q'}, 400)
                    shown_opts, shown_c = shuffled_opts(idx)
                    ter['cur_cell'] = idx
                    ter['phase'] = 'battle'
                    ter['shown_opts'] = shown_opts
                    ter['shown_c'] = shown_c
                    ter['winner'] = None
                    ter['wrong_teams'] = []
                    ter['last_msg'] = f'{idx+1}-sektor uchun jang boshlandi!'
                elif act == 'ter_reveal':
                    ter = state.get('ter')
                    if ter and ter['cur_cell'] is not None:
                        ter['phase'] = 'revealed'
                        ter['last_msg'] = 'Javob ochildi!'
                elif act == 'ter_sync_scores':
                    ter = state.get('ter')
                    if ter:
                        for t in range(4):
                            cnt = sum(1 for o in ter['owners'] if o == t)
                            state['scores'][t] += cnt * 100

                # --- BOMB ADMIN ---
                elif act == 'bomb_start':
                    sec = data.get('sec', 20)
                    try:
                        start_bomb_game(sec)
                    except Exception as e:
                        return self._json({'error': str(e)}, 400)
                elif act == 'bomb_resume':
                    bomb = state.get('bomb')
                    if not bomb or bomb['status'] == 'gameover':
                        return self._json({'error': 'Davom ettirib bo‘lmaydi'}, 400)
                    nxt = next_alive_team(bomb['lives'], bomb['holder'])
                    bomb['holder'] = nxt
                    bomb['idx'] += 1
                    bomb['cur_sec'] = bomb['base_sec']
                    bomb['deadline'] = time.time() + bomb['cur_sec']
                    bomb['status'] = 'playing'
                    bomb['last_choice'] = None
                    q_idx = bomb['order'][bomb['idx'] % len(bomb['order'])]
                    shown_opts, shown_c = shuffled_opts(q_idx)
                    bomb['shown_opts'] = shown_opts
                    bomb['shown_c'] = shown_c
                    bomb['last_msg'] = f'Yangi raund! Bomba {state["teams"][nxt]}da ({bomb["cur_sec"]}s)!'

                # --- JEOPARDY ADMIN ---
                elif act == 'open':
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
                        text_answers={}, ai_grades={}, ai_note='',
                        kahoot=None, mil=None, auc=None, ter=None, bomb=None
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
