import base64
import concurrent.futures
import copy
import io
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape as xml_esc

PORT = int(os.environ.get("PORT", 8080))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
AI_PRIMARY = os.environ.get("AI_PRIMARY", "auto").strip().lower()
DEFAULT_ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234").strip()


def _clean_tg_token(raw_val):
    t = str(raw_val or "").strip().strip('"').strip("'")
    if t.lower().startswith("bot") and ":" in t:
        t = t[3:].strip()
    return t


TELEGRAM_BOT_TOKEN = _clean_tg_token(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
APP_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "https://jeopardy-viym.onrender.com").strip().rstrip("/")
TG_BOT_INFO = {"ok": False, "username": "", "error": "Token kiritilmagan"}


def get_active_ai_list():
    providers = []
    if GEMINI_API_KEY:
        providers.append("Gemini")
    if OPENROUTER_API_KEY:
        providers.append("OpenRouter")
    if GROQ_API_KEY:
        providers.append("Groq")
    return providers


def is_economics_topic(topic):
    t = str(topic or "").lower()
    econ_keys = (
        "iqtisod", "moliya", "bank", "soliq", "byudjet", "korxona", "firma",
        "xarajat", "foyda", "tannarx", "ish haqi", "mehnat", "bozor", "savdo",
        "inflyatsiya", "yalpi", "yaim", "kredit", "investitsiya", "biznes",
        "marketing", "menejment", "buxgalter", "kapital", "aksiya", "valyuta",
        "eksport", "import", "monopoliya", "raqobat", "narx", "daromad", "renta",
    )
    return any(k in t for k in econ_keys)


ECON_LEAK_RE = re.compile(
    r"(UX\s*=\s*DX|Pc\s*=\s*s\s*\+\s*v|Sv\s*=\s*C\s*\+\s*v|F_?ich\s*=|R'\s*=\s*\(?R\s*/\s*W|VP\s*=\s*VH\s*/\s*R|ulgurji narx|avanslangan mablag)",
    re.IGNORECASE,
)


PRESETS_META = [
    {"id": "econ", "icon": "📈", "title": "Iqtisodiyot va Moliya", "desc": "Mikro va makroiqtisodiyot, bank tizimi, bozor va moliya"},
    {"id": "logic", "icon": "🧠", "title": "Mantiq va Zehn", "desc": "Mantiqiy masalalar, sonlar ketma-ketligi va tezkor fikrlash"},
    {"id": "history", "icon": "🏛️", "title": "O‘zbekiston va Jahon Tarixi", "desc": "Buyuk allomalar, Temuriylar davri va jahon sivilizatsiyasi"},
    {"id": "it", "icon": "💻", "title": "IT va Sun’iy Idrok", "desc": "Dasturlash, algoritmlar, sun’iy intellekt va kiberxavfsizlik"},
    {"id": "general", "icon": "🌍", "title": "Umumiy Bilimlar", "desc": "Geografiya, fan, adabiyot, sport va qiziqarli faktlar"},
]


def _pack(cats, items):
    res = []
    for c_idx, cat in enumerate(cats):
        for r_idx in range(5):
            q_txt, opts, c, exp = items[c_idx * 5 + r_idx]
            res.append({
                "cat": cat,
                "pts": (r_idx + 1) * 100,
                "q": q_txt,
                "opts": list(opts),
                "c": c,
                "ans": opts[c] if opts else "",
                "exp": exp,
            })
    return res


PRESET_DATA = {
    "econ": {
        "title": "Iqtisodiyot va Moliya",
        "questions": _pack(
            ["Mikroiqtisodiyot", "Makroiqtisodiyot", "Bank va Pul", "Xalqaro Savdo", "Biznes va Bozor"],
            [
                ("Tovar narxi oshganda unga bo‘lgan talab hajmining kamayishi nima deyiladi?", ["Talab qonuni", "Taklif qonuni", "Inflyatsiya", "Monopoliya"], 0, "Narx va talab hajmi o‘rtasida teskari bog‘liqlik mavjud."),
                ("Bozorda faqat bitta sotuvchi hukmronlik qiladigan tuzilma qanday nomlanadi?", ["Oligopoliya", "Monopoliya", "Raqobat", "Kartel"], 1, "Monopoliya sharoitida yagona ishlab chiqaruvchi narxni belgilaydi."),
                ("Qo‘shimcha 1 birlik mahsulot ishlab chiqarish uchun ketadigan xarajat nima?", ["Doimiy xarajat", "Chegaraviy xarajat (MC)", "O‘rtacha xarajat", "Sof foyda"], 1, "Marginal Cost (MC) — qo‘shimcha birlik xarajatidir."),
                ("Bir tovar narxi oshganda boshqasiga talab oshsa, ular qanday tovarlar?", ["O‘rinbosar (substitut)", "To‘ldiruvchi", "Past sifatli", "Jamoat tovari"], 0, "Masalan, choy va qahva o‘rinbosar tovarlardir."),
                ("Iste’molchining qo‘shimcha birlikdan oladigan qoniqishi kamayib borishi qonuni?", ["Gossenning 1-qonuni", "Sey qonuni", "Ouken qonuni", "Engel qonuni"], 0, "Chegaraviy naflilikning pasayib borish qonuni Gossen nomi bilan bog‘liq."),
                ("Mamlakat ichida bir yilda yaratilgan barcha pirovard tovar va xizmatlar qiymati?", ["YaIM (GDP)", "YaMM (GNP)", "Sof eksport", "Davlat byudjeti"], 0, "Yalpi ichki mahsulot (YaIM) hududiy tamoyil asosida hisoblanadi."),
                ("Narxlar umumiy darajasining uzoq muddatli o‘sishi va pul qadrsizlanishi?", ["Deflyatsiya", "Inflyatsiya", "Stagnatsiya", "Devalvatsiya"], 1, "Inflyatsiya pulning xarid qobiliyatini pasaytiradi."),
                ("Ishsizlik va inflyatsiya o‘rtasidagi teskari bog‘liqlikni ko‘rsatuvchi egri chiziq?", ["Fillips egri chizig‘i", "Laffer egri chizig‘i", "Lorens egri chizig‘i", "IS-LM modeli"], 0, "Fillips egri chizig‘i qisqa muddatda inflyatsiya va ishsizlik aloqasini ko‘rsatadi."),
                ("Soliq stavkasi va byudjet tushumlari bog‘liqligini ifodalovchi egri chiziq?", ["Laffer egri chizig‘i", "Engel chizig‘i", "Filips chizig‘i", "Gini koeffitsiyenti"], 0, "Haddan tashqari yuqori soliq stavkasi byudjet tushumlarini kamaytiradi."),
                ("YaIM o‘sishining ikki chorak ketma-ket pasayishi qanday ataladi?", ["Bum", "Retsessiya", "Giperinflyatsiya", "Emissiya"], 1, "Retsessiya iqtisodiy faollikning pasayish fazasidir."),
                ("O‘zbekiston Respublikasida pul-kredit siyosatini qaysi organ yuritadi?", ["Moliya vazirligi", "Markaziy bank", "Soliq qo‘mitasi", "Tijorat banklari"], 1, "Markaziy bank asosiy stavka va pul massasini tartibga soladi."),
                ("Markaziy bankning tijorat banklariga beradigan kreditlari bo‘yicha foiz ko‘rsatkichi?", ["Asosiy stavka", "Diskont", "Dividend", "Keshbek"], 0, "Asosiy stavka iqtisodiyotdagi kredit va depozit foizlariga ta’sir qiladi."),
                ("Aholi va korxonalarning bankka vaqtincha qo‘ygan pul mablag‘lari nima?", ["Kredit", "Depozit (omonat)", "Aksiya", "Veksel"], 1, "Depozit egasiga foiz daromadi keltiradi."),
                ("Kompaniya foydasidan aksiyadorlarga to‘lanadigan ulush qanday nomlanadi?", ["Foiz", "Dividend", "Renta", "Royalti"], 1, "Dividend aksiyalar soniga mutanosib taqsimlanadi."),
                ("Qarz majburiyatini tasdiqlovchi qimmatli qog‘oz nima deyiladi?", ["Obligatsiya", "Oddiy aksiya", "Litsenziya", "Patent"], 0, "Obligatsiya egasi belgilangan muddatda asosiy qarz va foiz oladi."),
                ("Eksport hajmi import hajmidan katta bo‘lsa, savdo balansi qanday bo‘ladi?", ["Profitsit (ijobiy)", "Defitsit (taqchil)", "Nolga teng", "Bankrot"], 0, "Sof eksport musbat bo‘lganda savdo profisiti yuzaga keladi."),
                ("Chet el tovarlariga qo‘yiladigan bojxona solig‘i qanday ataladi?", ["Tarif (boj)", "Kvota", "Subsidiya", "Demping"], 0, "Bojxona tarifi ichki bozorni himoya qilish va byudjetni to‘ldirish uchun qo‘llanadi."),
                ("Tovarni jahon bozorida tannarxidan ham arzon narxda sotish siyosati?", ["Demping", "Embargo", "Kliring", "Reeksport"], 0, "Demping raqobatchilarni bozordan siqib chiqarish maqsadida qo‘llanadi."),
                ("JST qisqartmasi nimani anglatadi?", ["Jahon Savdo Tashkiloti", "Jahon Soliq Tizimi", "Jamiyat Sanoat Tarmog‘i", "Janubiy Savdo Ittifoqi"], 0, "JST (WTO) xalqaro savdo qoidalarini tartibga soluvchi tashkilot."),
                ("Milliy valyuta kursining xorijiy valyutaga nisbatan rasmiy pasayishi?", ["Devalvatsiya", "Revalvatsiya", "Diversifikatsiya", "Denomizatsiya"], 0, "Devalvatsiya eksportchilarni rag‘batlantirishi mumkin."),
                ("Daromad va xarajatlar tenglashadigan ishlab chiqarish nuqtasi nima?", ["Zararsizlik nuqtasi", "Maksimal foyda", "Defolt nuqtasi", "Kapitalizatsiya"], 0, "Break-even point (zararsizlik nuqtasi)da sof foyda nolga teng."),
                ("Yangi tashkil etilgan innovatsion va tez o‘suvchi loyiha qanday ataladi?", ["Startap", "Holding", "Trast", "Syndikat"], 0, "Startaplar ko‘pincha venchur fondlar tomonidan moliyalashtiriladi."),
                ("Xatarlarni kamaytirish uchun mablag‘larni turli aktivlarga taqsimlash?", ["Diversifikatsiya", "Inflyatsiya", "Likvidlik", "Amortizatsiya"], 0, "«Barcha tuxumni bitta savatga solmaslik» tamoyili."),
                ("Aktivning tez va qiymatini yo‘qotmasdan naqd pulga aylanish qobiliyati?", ["Likvidlik", "Rentabellik", "Solventsiya", "Kapital"], 0, "Naqd pul eng yuqori likvidlikka ega aktivdir."),
                ("Mijozlarni jalb qilish va mahsulotni bozorga olib chiqish tizimi?", ["Marketing", "Logistika", "Audit", "Buxgalteriya"], 0, "Marketing 4P (Product, Price, Place, Promotion) tamoyiliga asoslanadi."),
            ],
        ),
    },
    "logic": {
        "title": "Mantiq va Zehn",
        "questions": _pack(
            ["Sonlar Qatori", "Topishmoqlar", "Strategiya", "Ehtimollik", "Tezkor Zehn"],
            [
                ("Ketma-ketlikni davom ettiring: 2, 6, 12, 20, 30, ?", ["40", "42", "44", "36"], 1, "Farqlar +4, +6, +8, +10, +12 tarzida ortib bormoqda: 30 + 12 = 42."),
                ("Ketma-ketlikda keyingi son qaysi: 1, 1, 2, 3, 5, 8, 13, ?", ["18", "20", "21", "24"], 2, "Fibonachchi sonlari: har bir son oldingi ikkitasining yig‘indisi (8 + 13 = 21)."),
                ("Qatorni to‘ldiring: 3, 9, 27, 81, ?", ["162", "243", "324", "108"], 1, "Har bir had 3 ga ko‘paytirilmoqda: 81 × 3 = 243."),
                ("Qaysi son ortiqcha: 4, 9, 16, 24, 36?", ["9", "16", "24", "36"], 2, "Boshqa barcha sonlar butun sonlarning kvadrati (2², 3², 4², 6²), 24 esa emas."),
                ("5 ta mashina 5 detalni 5 daqiqada yasasa, 100 mashina 100 detalni necha daqiqada yasaydi?", ["100 daqiqada", "20 daqiqada", "5 daqiqada", "1 daqiqada"], 2, "Har bir mashina 1 detalni 5 daqiqada yasaydi, demak 100 mashina ham 5 daqiqada bitiradi."),
                ("Qorong‘i xonada 1 ta gugurt, sham, kerosin lampa va o‘tin bor. Avval nimani yoqasiz?", ["Shamni", "Gugurtni", "O‘tinni", "Lampani"], 1, "Boshqa narsalarni yoqish uchun avval gugurtni yoqish kerak."),
                ("Kechasi soat 12 da yomg‘ir yog‘ayotgan bo‘lsa, 72 soatdan keyin quyosh chiqishi mumkinmi?", ["Ha", "Yo‘q, tun bo‘ladi", "Faqat qishda", "Aniq emas"], 1, "72 soat = roppa-rosa 3 sutka, demak yana yarim tun (soat 12:00) bo‘ladi."),
                ("Daraxtda 10 ta qush o‘tirgan edi. Ovchi 1 tasini otdi. Daraxtda nechta qush qoldi?", ["9 ta", "1 ta", "0 ta (uchib ketdi)", "10 ta"], 2, "O‘q ovozidan qolgan qushlar uchib ketadi."),
                ("Qaysi oyda 28 kun bor?", ["Faqat fevralda", "Barcha 12 oyda", "Martda", "Dekabrda"], 1, "Har bir oyda kamida 28 kun mavjud."),
                ("Otasi 40 yoshda, o‘g‘li 10 yoshda. Necha yildan keyin otasi o‘g‘lidan 3 barobar katta bo‘ladi?", ["5 yildan keyin", "10 yildan keyin", "15 yildan keyin", "20 yildan keyin"], 0, "5 yildan keyin ota 45, o‘g‘il 15 yoshda bo‘ladi (45 / 15 = 3)."),
                ("3 ta mushuk 3 sichqonni 3 daqiqada tutadi. 1 mushuk 1 sichqonni necha daqiqada tutadi?", ["1 daqiqada", "3 daqiqada", "9 daqiqada", "2 daqiqada"], 1, "Har bir mushuk o‘z sichqonini 3 daqiqa davomida quvib tutadi."),
                ("Poygada 2-o‘rindagi sportchini quvib o‘tsangiz, nechanchi o‘ringa chiqasiz?", ["1-o‘ringa", "2-o‘ringa", "3-o‘ringa", "4-o‘ringa"], 1, "2-o‘rindagi odamning o‘rnini egallaysiz — ya’ni 2-o‘rin."),
                ("Stolda 4 ta olma bor. Siz 2 tasini oldingiz. Sizda nechta olma bor?", ["2 ta", "4 ta", "1 ta", "0 ta"], 0, "Siz olgan 2 ta olma o‘zingizda turibdi."),
                ("Qaysi so‘z hamma tillarda bir xil eshitiladi?", ["Salom", "Exo (aks-sado)", "Suv", "Kitob"], 1, "Aks-sado aytilgan so‘zni aynan qaytaradi."),
                ("Bir tayoqning 2 ta uchi bor. Yarimta tayoqning nechta uchi bor?", ["1 ta", "2 ta", "3 ta", "4 ta"], 1, "Kesilgan tayoqning ham baribir 2 ta uchi bo‘ladi."),
                ("Tanga 2 marta tashlandi. Ikkala safar ham gerb tushish ehtimoli qancha?", ["50%", "25%", "75%", "10%"], 1, "1/2 × 1/2 = 1/4 = 25%."),
                ("O‘yin kubigi (1–6) bir marta tashlandi. Juft son tushish ehtimoli qancha?", ["1/6", "1/3", "1/2", "2/3"], 2, "Juft sonlar 3 ta (2, 4, 6), jami 6 ta: 3/6 = 1/2."),
                ("Qutida 5 oq va 5 qora shar bor. Kamida nechta shar olsangiz albatta 2 ta bir xil rangli chiqadi?", ["2 ta", "3 ta", "6 ta", "5 ta"], 1, "Dirixle tamoyili: 2 xil rang bo‘lgani uchun 3 ta shar olinsa kamida ikkitasi bir xil bo‘ladi."),
                ("3 ta tangadan biri soxta (yengilroq). Pallali tarozida kamida necha marta tortib uni topish mumkin?", ["1 marta", "2 marta", "3 marta", "4 marta"], 0, "2 tasini pallaga qo‘yasiz: teng bo‘lsa 3-si soxta, biri ko‘tarilsa o‘shanisi soxta."),
                ("Soat 3:15 da soat va minut millari orasidagi burchak necha gradus?", ["0°", "7.5°", "15°", "30°"], 1, "Minut mili 3 da, soat mili esa 3 dan chorak soat (30° / 4 = 7.5°) siljigan."),
                ("Uchta 2 raqami yordamida eng katta qanday son yozish mumkin?", ["222", "2^22", "22^2", "2×2×2"], 1, "2 ning 22-darajasi (4 194 304) eng katta qiymat beradi."),
                ("Suv qachon elakda turadi?", ["Muzlaganda", "Qaynaganda", "Hech qachon", "Kechasi"], 0, "Muz holatida suv elakdan o‘tmaydi."),
                ("Qaysi idishdan ovqat yeb bo‘lmaydi?", ["Bo‘sh idishdan", "Katta idishdan", "Shisha idishdan", "Chuqur idishdan"], 0, "Bo‘sh idishda ovqat bo‘lmaydi."),
                ("1 kg tosh og‘irmi yoki 1 kg paxta?", ["Tosh", "Paxta", "Ikkalasi teng", "Bilmayman"], 2, "Ikkalasining ham vazni 1 kilogrammdan."),
                ("Yomg‘ir yog‘ayotganda qarg‘a qanday daraxtga qo‘nadi?", ["Ho‘l daraxtga", "Baland daraxtga", "Quruq daraxtga", "Past daraxtga"], 0, "Yomg‘ir yog‘ayotgani uchun daraxt ho‘l bo‘ladi."),
            ],
        ),
    },
    "history": {
        "title": "O‘zbekiston va Jahon Tarixi",
        "questions": _pack(
            ["Buyuk Allomalar", "Temuriylar Davri", "Ipak Yo‘li", "Jahon Tarixi", "Yangi O‘zbekiston"],
            [
                ("«Al-jabr val-muqobala» asari muallifi kim?", ["Al-Xorazmiy", "Al-Farg‘oniy", "Ibn Sino", "Al-Beruniy"], 0, "Algebra atamasi Al-Xorazmiyning ushbu asari nomidan olingan."),
                ("Yer sharining radiusini o‘rta asrlarda eng aniq o‘lchagan vatandoshimiz?", ["Al-Beruniy", "Ulug‘bek", "Al-Buxoriy", "Zamahshariy"], 0, "Abu Rayhon Beruniy Hindistonda Yer radiusini 6339.6 km etib hisoblagan."),
                ("«Tib qonunlari» asari necha kitobdan iborat?", ["3 kitob", "5 kitob", "7 kitob", "10 kitob"], 1, "Ibn Sinoning «Tib qonunlari» 5 kitobdan iborat."),
                ("1018 ta yulduz koordinatalarini o‘z ichiga olgan «Ziji jadidi Ko‘ragoniy» muallifi?", ["Mirzo Ulug‘bek", "Ali Qushchi", "Qozizoda Rumiy", "Alisher Navoiy"], 0, "Samarqand rasadxonasida tuzilgan yulduzlar jadvali."),
                ("«Xamsa»ni turkiy tilda birinchi bo‘lib yaratgan buyuk mutafakkir?", ["Alisher Navoiy", "Zahiriddin Bobur", "Lutfiy", "Jomiy"], 0, "Alisher Navoiy 1483–1485-yillarda besh dostondan iborat «Xamsa»ni yozgan."),
                ("Amir Temur qaysi yili Movarounnahr taxtini egallagan?", ["1360-yil", "1370-yil", "1380-yil", "1405-yil"], 1, "1370-yilda Samarqand poytaxt etib belgilangan."),
                ("«Boburnoma» asari qaysi tilda yozilgan?", ["Fors tilida", "Eski o‘zbek tilida", "Arab tilida", "Hind tilida"], 1, "Bobur o‘z memuarini jonli eski o‘zbek tilida yozgan."),
                ("Samarqanddagi Registon maydonida joylashgan eng birinchi madrasa?", ["Ulug‘bek madrasasi", "Sherdor madrasasi", "Tillakori madrasa", "Bibixonim madrasasi"], 0, "Ulug‘bek madrasasi 1417–1420-yillarda qurilgan."),
                ("Amir Temurning mashhur shiori qaysi?", ["«Kuch — adolatdadir»", "«Bilim — boylik»", "«Tinchlik — oliy ne’mat»", "«Harakatda barakat»"], 0, "«Rosti — rusti» (Kuch — adolatdadir) Amir Temur uzugida o‘yib yozilgan."),
                ("Temuriylar davrida «Sharq Rafaeli» nomini olgan buyuk musavvir?", ["Kamoliddin Behzod", "Sulton Ali Mashhadiy", "Xondamir", "Mirkhond"], 0, "Kamoliddin Behzod Hirot miniatyura maktabining eng yirik namoyandasi."),
                ("Buyuk Ipak yo‘li qaysi asrda shakllangan?", ["Mil. avv. II asrda", "Milodiy V asrda", "X asrda", "XV asrda"], 0, "Xitoy elchisi Chjan Syanning G‘arbga sayohatidan so‘ng yo‘l ochilgan."),
                ("Qog‘oz ishlab chiqarish VIII asrda Xitoydan so‘ng qaysi shaharda rivojlangan?", ["Samarqandda", "Buxoroda", "Xivada", "Toshkentda"], 0, "Samarqand qog‘ozi o‘zining silliqligi va chidamliligi bilan mashhur bo‘lgan."),
                ("Buyuk Ipak yo‘lining asosiy tovari nima edi?", ["Ipak matolar", "Neft", "Paxta", "Kauchuk"], 0, "Xitoy ipagi G‘arb mamlakatlarida oltin bilan teng baholangan."),
                ("Buxorodagi mashhur Minorai Kalon qaysi hukmdor davrida qurilgan?", ["Arslonxon", "Ismoil Somoniy", "Abdullaxon II", "Amir Nasrullo"], 0, "1127-yilda Qoraxoniylar hukmdori Arslonxon tomonidan bunyod etilgan."),
                ("O‘zbekistondagi qaysi shaharlar UNESCO Umumjahon merosi ro‘yxatiga kiritilgan?", ["Samarqand, Buxoro, Xiva, Shahrisabz", "Faqat Samarqand", "Toshkent va Farg‘ona", "Nukus va Termiz"], 0, "To‘rtta tarixiy shahar markazlari UNESCO himoyasiga olingan."),
                ("Qadimgi Misr ehromlari qaysi maqsadda qurilgan?", ["Fir’avnlar maqbarasi", "Rasadxona", "Suv ombori", "Qal’a"], 0, "Giza ehromlari fir’avnlar uchun abadiy maqbara bo‘lgan."),
                ("Amerikani 1492-yilda kashf etgan dengizchi sayyoh kim?", ["Xristofor Kolumb", "Vasko da Gama", "Fernando Magellan", "Amerigo Vespuchchi"], 0, "Kolumb Hindistonga g‘arbiy yo‘l izlab Amerika qit’asiga yetib borgan."),
                ("Birinchi jahon urushi qaysi yillarda bo‘lib o‘tgan?", ["1914–1918", "1939–1945", "1904–1905", "1917–1922"], 0, "1914-yil iyulda boshlanib, 1918-yil noyabrda yakunlangan."),
                ("Birlashgan Millatlar Tashkiloti (BMT) qachon tashkil etilgan?", ["1945-yil", "1919-yil", "1950-yil", "1991-yil"], 0, "Ikkinchi jahon urushidan so‘ng tinchlikni saqlash maqsadida tuzilgan."),
                ("Insoniyat tarixida birinchi bo‘lib kosmosga uchgan fazogir?", ["Yuriy Gagarin", "Nil Armstrong", "Valentina Tereshkova", "Solijon Sharipov"], 0, "1961-yil 12-aprelda «Vostok-1» kemasida parvoz qilgan."),
                ("O‘zbekiston Respublikasi Davlat mustaqilligi qachon e’lon qilingan?", ["1991-yil 31-avgust", "1992-yil 8-dekabr", "1991-yil 18-noyabr", "1992-yil 2-iyul"], 0, "1991-yil 31-avgustda e’lon qilinib, 1-sentabr Mustaqillik kuni etib belgilangan."),
                ("O‘zbekiston Respublikasi Konstitutsiyasi qachon qabul qilingan?", ["1992-yil 8-dekabr", "1991-yil 1-sentabr", "1994-yil 1-iyul", "1993-yil 2-sentabr"], 0, "1992-yil 8-dekabrda Oliy Kengash sessiyasida qabul qilingan."),
                ("Milliy valyutamiz — «So‘m» qachon muomalaga kiritilgan?", ["1994-yil 1-iyul", "1991-yil 31-avgust", "1992-yil 10-dekabr", "1995-yil 1-yanvar"], 0, "1994-yil 1-iyuldan so‘m rasmiy to‘lov vositasi bo‘ldi."),
                ("O‘zbekiston BMTga qachon a’zo bo‘lgan?", ["1992-yil 2-mart", "1991-yil 1-sentabr", "1995-yil 24-oktabr", "2001-yil 15-iyun"], 0, "1992-yil 2-martda BMT Bosh Assambleyasi qarori bilan a’zo bo‘lgan."),
                ("Yangi tahrirdagi O‘zbekiston Konstitutsiyasi referendumida qachon qabul qilindi?", ["2023-yil 30-aprel", "2021-yil 24-oktabr", "2022-yil 8-dekabr", "2024-yil 1-yanvar"], 0, "2023-yil 30-apreldagi referendumda yangi tahrir qabul qilindi."),
            ],
        ),
    },
    "it": {
        "title": "IT va Sun’iy Idrok",
        "questions": _pack(
            ["Dasturlash", "Sun’iy Idrok", "Internet va Tarmoq", "Kiberxavfsizlik", "Texnologiyalar"],
            [
                ("Python dasturlash tilining yaratuvchisi kim?", ["Gvido van Rossum", "Linus Torvalds", "Jeyms Gosling", "Bjarne Stroustrup"], 0, "Gvido van Rossum Python tilini 1991-yilda taqdim etgan."),
                ("Veb-sahifalarning tuzilishini belgilovchi belgilash tili qaysi?", ["HTML", "Python", "SQL", "C++"], 0, "HyperText Markup Language (HTML) sahifa skeletini yaratadi."),
                ("Ma’lumotlar bazasi bilan ishlash uchun qo‘llaniladigan so‘rov tili?", ["SQL", "CSS", "JSON", "XML"], 0, "Structured Query Language (SQL) jadvallardan ma’lumot olish uchun ishlatiladi."),
                ("Dasturdagi xatoliklarni topish va tuzatish jarayoni nima deyiladi?", ["Debugging", "Compiling", "Hosting", "Phishing"], 0, "Debugging dastur kodidagi xatolarni bartaraf etish jarayonidir."),
                ("O‘zgaruvchida faqat True yoki False qiymat saqlaydigan ma’lumot turi?", ["Boolean", "Integer", "String", "Float"], 0, "Mantiqiy tur (Boolean) ikkita qiymat qabul qiladi."),
                ("ChatGPT va Gemini kabi matn yaratuvchi modellar qanday qisqartma bilan ataladi?", ["LLM", "CPU", "VPN", "BIOS"], 0, "Katta til modellari (LLM) milliardlab matnlar asosida o‘qitiladi."),
                ("Kompyuterning inson kabi fikrlay olishini sinovdan o‘tkazuvchi mashhur test?", ["Tyuring testi", "Eynshteyn testi", "Nyuton qonuni", "Moor qonuni"], 0, "Alan Tyuring 1950-yilda mashina intellektini baholash testini taklif qilgan."),
                ("Sun’iy neyron tarmoqlar inson miyasidagi qaysi hujayralardan ilhomlangan?", ["Neyronlardan", "Leykotsitlardan", "Eritrotsitlardan", "Trombotsitlardan"], 0, "Sun’iy neyronlar kirish signallarini vaznlar orqali qayta ishlaydi."),
                ("Tasvirlarni tanish va tahlil qilish bilan shug‘ullanuvchi AI yo‘nalishi?", ["Computer Vision", "Blockchain", "Cloud Storage", "DevOps"], 0, "Kompyuter ko‘rishi yuzni tanish va avtopilotlarda qo‘llanadi."),
                ("AI modeliga aniq va sifatli topshiriq yozish san’ati nima deyiladi?", ["Prompt Engineering", "Reverse Engineering", "Data Mining", "Web Scraping"], 0, "To‘g‘ri tuzilgan prompt AI javobi sifatini keskin oshiradi."),
                ("HTTP protokolidan farqli o‘laroq, ma’lumotlarni shifrlab uzatuvchi xavfsiz protokol?", ["HTTPS", "FTP", "SMTP", "POP3"], 0, "HTTPS SSL/TLS shifrlash sertifikatidan foydalanadi."),
                ("Domen nomlarini IP-manzillarga aylantirib beruvchi tizim nima?", ["DNS", "RAM", "SSD", "USB"], 0, "Domain Name System (DNS) internetning telefon kitobi vazifasini bajaradi."),
                ("Foydalanuvchining brauzerida saqlanadigan kichik matnli ma’lumot fayllari?", ["Cookies", "Pixels", "Drivers", "Kernels"], 0, "Cookie fayllari sessiya va sozlamalarni eslab qolish uchun ishlatiladi."),
                ("GitHub platformasi asosan nima uchun xizmat qiladi?", ["Kodlarni saqlash va boshqarish", "Video montaj qilish", "Musiqa tinglash", "Online o‘yin o‘ynash"], 0, "GitHub Git versiyalarni boshqarish tizimiga asoslangan."),
                ("«Cloud computing» (Bulutli texnologiya) nimani anglatadi?", ["Masofaviy server resurslaridan foydalanish", "Ob-havoni bashorat qilish", "Wi-Fi parolini buzish", "Fleshka xotirasi"], 0, "Render, AWS va Google Cloud bulutli platformalarga misoldir."),
                ("Soxta xat yoki sayt orqali foydalanuvchi parolini o‘g‘irlash usuli?", ["Phishing (Fishing)", "Backup", "Encryption", "Firewall"], 0, "Fishingda firibgarlar rasmiy bank yoki sayt qiyofasiga kiradi."),
                ("Akkauntga kirishda paroldan tashqari SMS yoki ilova kodi so‘ralishi nima?", ["Ikki bosqichli autentifikatsiya (2FA)", "Keshlash", "Arxivlash", "Formatlash"], 0, "2FA akkaunt xavfsizligini bir necha barobar oshiradi."),
                ("Tarmoqqa ruxsatsiz kirishlarni to‘suvchi himoya devori qanday ataladi?", ["Firewall", "Trojan", "Spam", "Cookie"], 0, "Firewall kiruvchi va chiquvchi trafikni filtrlaydi."),
                ("Fayllarni shifrlab, ochish uchun pul talab qiluvchi zararli dastur?", ["Ransomware", "Antivirus", "Browser", "Compiler"], 0, "Ransomware hujumlaridan himoyalanish uchun zaxira nusxa (backup) muhim."),
                ("Kuchli parol kamida nechta belgidan iborat bo‘lishi tavsiya etiladi?", ["12 ta va undan ko‘p", "4 ta raqam", "6 ta harf", "Faqat tug‘ilgan yil"], 0, "Katta-kichik harflar, raqam va maxsus belgilardan iborat uzun parol xavfsiz."),
                ("1 Kilobayt necha baytga teng?", ["1024 bayt", "100 bayt", "512 bayt", "2048 bayt"], 0, "Ikkilik sanoq tizimida 2^10 = 1024 bayt."),
                ("Kompyuterning vaqtinchalik tezkor xotirasi qaysi?", ["RAM", "HDD", "SSD", "DVD"], 0, "Kompyuter o‘chganda RAM xotiradagi ma’lumotlar tozalanadi."),
                ("Linux operatsion tizimi yadrosini kim yaratgan?", ["Linus Torvalds", "Bill Geyts", "Stiv Jobs", "Mark Sukerberg"], 0, "Linus Torvalds 1991-yilda Linux yadrosini e’lon qilgan."),
                ("QR-kod qisqartmasidagi «QR» nimani bildiradi?", ["Quick Response", "Quality Rate", "Quantum Radio", "Query Result"], 0, "QR-kod 1994-yilda Yaponiyada ixtiro qilingan."),
                ("Blokcheyn texnologiya asosida yaratilgan birinchi kriptovalyuta?", ["Bitcoin", "Ethereum", "Solana", "Dogecoin"], 0, "Bitcoin 2009-yilda Satoshi Nakamoto taxallusi ostida ishga tushirilgan."),
            ],
        ),
    },
    "general": {
        "title": "Umumiy Bilimlar",
        "questions": _pack(
            ["Geografiya", "Fan va Tabiat", "Adabiyot", "Sport", "Qiziqarli Faktlar"],
            [
                ("Dunyodagi eng katta okean qaysi?", ["Tinch okeani", "Atlantika okeani", "Hind okeani", "Shimoliy Muz okeani"], 0, "Tinch okeani Yer yuzasining qariyb uchdan bir qismini egallaydi."),
                ("Dunyodagi eng baland cho‘qqi qaysi?", ["Everest (Jomolungma)", "K2", "Elbrus", "Kilimanjaro"], 0, "Everest cho‘qqisi dengiz sathidan 8848 metr balandlikda joylashgan."),
                ("O‘zbekiston nechta davlat bilan chegaradosh?", ["5 ta", "4 ta", "6 ta", "7 ta"], 0, "Qozog‘iston, Qirg‘iziston, Tojikiston, Turkmaniston va Afg‘oniston."),
                ("Dunyodagi eng uzun daryo qaysi?", ["Nil", "Amudaryo", "Dunay", "Volga"], 0, "Nil daryosining uzunligi 6650 kilometrdan oshadi."),
                ("Qaysi qit’ada birorta ham cho‘l yo‘q?", ["Yevropa", "Afrika", "Avstraliya", "Osiyo"], 0, "Yevropa cho‘l zonasiga ega bo‘lmagan yagona qit’adir."),
                ("Quyosh sistemasidagi eng katta sayyora qaysi?", ["Yupiter", "Saturn", "Mars", "Yer"], 0, "Yupiterning massasi qolgan barcha sayyoralar yig‘indisidan ham katta."),
                ("Suvning kimyoviy formulasi qanday?", ["H2O", "CO2", "NaCl", "O2"], 0, "Ikki vodorod va bir kislorod atomidan tashkil topgan."),
                ("Yorug‘lik tezligi taxminan qanchaga teng?", ["300 000 km/s", "340 m/s", "150 000 km/s", "30 000 km/s"], 0, "Vakuumda yorug‘lik soniyasiga 299 792 km tezlikda tarqaladi."),
                ("O‘simliklarning yorug‘lik energiyasi yordamida organik modda hosil qilish jarayoni?", ["Fotosintez", "Diffuziya", "Osmos", "Bug‘lanish"], 0, "Fotosintez jarayonida kislorod ajralib chiqadi."),
                ("Inson tanasidagi eng katta organ qaysi?", ["Teri", "Jigar", "O‘pka", "Yurak"], 0, "Teri inson tana vaznining taxminan 15 foizini tashkil qiladi."),
                ("«O‘tkan kunlar» romanining muallifi kim?", ["Abdulla Qodiriy", "Cho‘lpon", "Oybek", "G‘afur G‘ulom"], 0, "O‘zbek romanchiligi maktabining asoschisi Abdulla Qodiriy asari."),
                ("«Shum bola» qissasining bosh qahramoni ismi nima?", ["Qoravoy", "Otabek", "Yodgor", "Hoshimjon"], 0, "G‘afur G‘ulomning mashhur hajviy qissasi qahramoni."),
                ("«Sariq devni minib» asarini kim yozgan?", ["Xudoyberdi To‘xtaboyev", "O‘tkir Hoshimov", "Tohir Malik", "Said Ahmad"], 0, "Hoshimjonning sehrli qalpoqchasi haqidagi mashhur asar."),
                ("«Urush va tinchlik» romani muallifi kim?", ["Lev Tolstoy", "Fyodor Dostoyevskiy", "Anton Chexov", "Aleksandr Pushkin"], 0, "Jahon adabiyotining eng yirik epopeya romanlaridan biri."),
                ("«Dunyoning ishlari» asari muallifi kim?", ["O‘tkir Hoshimov", "Pirimqul Qodirov", "Odil Yoqubov", "Erkin Vohidov"], 0, "Ona siymosiga bag‘ishlangan samimiy novellalar to‘plami."),
                ("Olimpiya o‘yinlari necha yilda bir marta o‘tkaziladi?", ["4 yilda", "2 yilda", "5 yilda", "3 yilda"], 0, "Yozgi va qishki Olimpiada o‘yinlari har 4 yilda o‘tkaziladi."),
                ("Futbol maydonida bir jamoadan nechta o‘yinchi o‘ynaydi?", ["11 ta", "9 ta", "10 ta", "12 ta"], 0, "10 ta maydon o‘yinchisi va 1 ta darvozabon."),
                ("Shaxmat taxtasida jami nechta katak bor?", ["64 ta", "32 ta", "81 ta", "100 ta"], 0, "8×8 o‘lchamdagi 32 oq va 32 qora katakdan iborat."),
                ("Nodirbek Abdusattorov 2021-yilda qaysi yo‘nalishda jahon chempioni bo‘ldi?", ["Rapid (tezkor shaxmat)", "Klassik shaxmat", "Blits", "Shashka"], 0, "17 yoshida Rapid bo‘yicha eng yosh jahon chempioniga aylangan."),
                ("Basketbol savatchasining yerdan balandligi necha metr?", ["3.05 m", "2.50 m", "3.50 m", "2.80 m"], 0, "Standart balandlik 10 fut (3.05 metr)ga teng."),
                ("Asalarilar necha ko‘zga ega?", ["5 ta", "2 ta", "4 ta", "8 ta"], 0, "2 ta katta murakkab va 3 ta kichik oddiy ko‘zi bor."),
                ("Eyfel minorasi qaysi shaharda joylashgan?", ["Parijda", "Londonda", "Rimda", "Madridda"], 0, "1889-yilda Fransiya poytaxti Parijda qurilgan."),
                ("Dunyodagi eng tez yuguruvchi quruqlik hayvoni?", ["Gepard", "Sher", "Ot", "Bo‘ri"], 0, "Gepard qisqa masofada soatiga 110–120 km tezlikka chiqa oladi."),
                ("Kamalakda nechta asosiy rang bor?", ["7 ta", "5 ta", "6 ta", "9 ta"], 0, "Qizil, zarg‘aldoq, sariq, yashil, havorang, ko‘k, binafsha."),
                ("Bir sutkada necha soniya bor?", ["86 400", "3 600", "14 400", "43 200"], 0, "24 soat × 60 daqiqa × 60 soniya = 86 400 soniya."),
            ],
        ),
    },
}

MIL_PRIZES = [100, 200, 300, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000, 125000, 250000, 500000, 1000000]
MIL_SAFES = [4, 9, 14]


def _call_gemini_raw(prompt_text, file_part=None, json_mode=False):
    parts = []
    if file_part:
        parts.append({"inline_data": {"mime_type": file_part["mime"], "data": file_part["b64"]}})
    parts.append({"text": prompt_text})

    candidates = []
    for m in (
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-flash-latest",
        GEMINI_MODEL,
    ):
        if m and m not in candidates:
            candidates.append(m)

    gen_cfg = {"temperature": 0.65}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"

    payload = json.dumps({"contents": [{"parts": parts}], "generationConfig": gen_cfg}).encode("utf-8")
    last_err = "Gemini serverlari band (503)."

    for model_name in candidates:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(model_name)}:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}"
        )
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cands = data.get("candidates") or []
            if not cands:
                raise RuntimeError("Gemini bo‘sh javob qaytardi.")
            out_parts = cands[0].get("content", {}).get("parts", [])
            text_out = "".join(p.get("text", "") for p in out_parts).strip()
            if text_out:
                return text_out
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code in (400, 404):
                continue
            if e.code in (429, 500, 502, 503, 504):
                last_err = f"Gemini band ({e.code})"
                continue
            raise RuntimeError(f"Gemini xatosi ({e.code}): {err_body[:140]}")
        except Exception as ex:
            last_err = str(ex)
            continue
    raise RuntimeError(last_err)


def _call_openrouter_raw(prompt_text, file_part=None, json_mode=False):
    if file_part and not str(file_part.get("mime", "")).startswith("image/"):
        raise RuntimeError("OpenRouter PDF faylni bevosita o‘qimaydi (.docx yoki .txt yuklang).")

    p_txt = prompt_text + ("\n\nFaqat toza JSON obyekt qaytar, ``` yoki ortiqcha matn yozma." if json_mode else "")
    content = [{"type": "text", "text": p_txt}]
    if file_part and str(file_part.get("mime", "")).startswith("image/"):
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{file_part['mime']};base64,{file_part['b64']}"},
        })

    models = []
    for m in (
        OPENROUTER_MODEL,
        "openrouter/free",
        "google/gemma-3-27b-it:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
    ):
        if m and m not in models:
            models.append(m)

    last_err = "OpenRouter javob bermadi."
    for model_name in models:
        body_obj = {
            "model": model_name,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.65,
        }
        req = urllib.request.Request(
            "[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)",
            data=json.dumps(body_obj).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": APP_PUBLIC_URL,
                "X-Title": "Jeo Quiz Pro",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            txt = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
            if txt:
                return txt
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            last_err = f"OpenRouter xatosi ({e.code}): {err_body[:140]}"
            if e.code == 401:
                break
        except Exception as ex:
            last_err = str(ex)
    raise RuntimeError(last_err)


def _call_groq_raw(prompt_text, file_part=None, json_mode=False):
    if file_part and not str(file_part.get("mime", "")).startswith("image/"):
        raise RuntimeError("Groq PDF faylni bevosita o‘qimaydi (.docx yoki .txt yuklang).")

    content = [{"type": "text", "text": prompt_text}]
    models = []
    if file_part and str(file_part.get("mime", "")).startswith("image/"):
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{file_part['mime']};base64,{file_part['b64']}"},
        })
        models = ["meta-llama/llama-4-scout-17b-16e-instruct"]
    else:
        for m in (GROQ_MODEL, "llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
            if m and m not in models:
                models.append(m)

    last_err = "Groq AI javob bermadi."
    for model_name in models:
        body_obj = {
            "model": model_name,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.65,
        }
        if json_mode and "scout" not in model_name:
            body_obj["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            "[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)",
            data=json.dumps(body_obj).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "User-Agent": "Mozilla/5.0 (compatible; JeoQuiz/1.0)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            txt = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
            if txt:
                return txt
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            last_err = f"Groq xatosi ({e.code}): {err_body[:140]}"
            if e.code == 401:
                break
        except Exception as ex:
            last_err = str(ex)
    raise RuntimeError(last_err)


def call_gemini(prompt_text, file_part=None, json_mode=False, preferred=None):
    available = {}
    if GEMINI_API_KEY:
        available["gemini"] = _call_gemini_raw
    if OPENROUTER_API_KEY:
        available["openrouter"] = _call_openrouter_raw
    if GROQ_API_KEY:
        available["groq"] = _call_groq_raw

    if not available:
        raise RuntimeError("Serverda GEMINI_API_KEY, OPENROUTER_API_KEY yoki GROQ_API_KEY kiritilmagan.")

    pref = (preferred or AI_PRIMARY or "auto").lower()
    order = []
    if pref in available:
        order.append(pref)
    for k in ("gemini", "openrouter", "groq"):
        if k in available and k not in order:
            order.append(k)

    errors = []
    for prov in order:
        try:
            return available[prov](prompt_text, file_part=file_part, json_mode=json_mode)
        except Exception as e:
            errors.append(f"{prov.upper()}: {e}")
    raise RuntimeError("503: AI serverlari band (" + " | ".join(errors) + ")")


def extract_json_block(raw):
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    txt = m.group(1).strip() if m else raw.strip()
    try:
        return json.loads(txt)
    except Exception:
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(txt[start:end + 1])
        raise


def extract_docx_text(b64_data):
    raw_bytes = base64.b64decode(b64_data)
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    texts = [el.text for el in root.iter() if el.tag.endswith("}t") and el.text]
    return " ".join(texts)[:28000]


def fetch_topic_image_bytes(query):
    q = str(query or "").strip()
    if not q:
        return None, None
    try:
        api_url = (
            "[https://en.wikipedia.org/w/api.php?action=query&generator=search](https://en.wikipedia.org/w/api.php?action=query&generator=search)"
            f"&gsrsearch={urllib.parse.quote(q)}&gsrlimit=4&prop=pageimages&pithumbsize=800&format=json"
        )
        req = urllib.request.Request(api_url, headers={"User-Agent": "JeoQuizPro/1.0 ([https://jeopardy-viym.onrender.com](https://jeopardy-viym.onrender.com))"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pages = ((data.get("query") or {}).get("pages") or {}).values()
        for pg in sorted(pages, key=lambda x: x.get("index", 99)):
            thumb = (pg.get("thumbnail") or {}).get("source", "")
            low = thumb.lower().split("?")[0]
            if low.endswith((".jpg", ".jpeg", ".png")):
                ext = "png" if low.endswith(".png") else "jpg"
                ireq = urllib.request.Request(thumb, headers={"User-Agent": "JeoQuizPro/1.0"})
                with urllib.request.urlopen(ireq, timeout=7) as iresp:
                    ibytes = iresp.read()
                if 2000 < len(ibytes) < 2_500_000:
                    return ibytes, ext
    except Exception:
        pass
    return None, None


def normalize_slide_item(raw_item, idx, allow_econ=True):
    layout = str(raw_item.get("layout") or ("cover" if idx == 0 else "split_image")).strip().lower()
    valid_layouts = (
        "cover", "split_image", "formula_model", "table_matrix",
        "diagram_flow", "comparison", "stats_chart", "bullets", "split", "stats", "quote", "summary",
    )
    if layout not in valid_layouts:
        layout = "split_image"

    def _clean_txt(val):
        s = str(val or "").strip()
        if not allow_econ and ECON_LEAK_RE.search(s):
            return ""
        return s

    bullets = [_clean_txt(b) for b in (raw_item.get("bullets") or []) if _clean_txt(b)][:5]
    stats_raw = raw_item.get("stats") or []
    stats = []
    for st in stats_raw[:4]:
        if isinstance(st, dict):
            lbl = _clean_txt(st.get("label"))
            val = _clean_txt(st.get("value"))
            pct = st.get("pct")
            try:
                pct_num = max(10, min(100, int(float(str(pct).replace("%", ""))))) if pct is not None else 75
            except Exception:
                pct_num = 75
            if lbl or val:
                stats.append({"label": lbl, "value": val, "pct": pct_num})

    d_steps_raw = raw_item.get("diagram_steps") or []
    d_steps = []
    for s_i, ds in enumerate(d_steps_raw[:4]):
        if isinstance(ds, dict):
            st_lbl = _clean_txt(ds.get("label") or ds.get("title") or f"{s_i + 1}-bosqich")
            st_desc = _clean_txt(ds.get("desc") or ds.get("text"))
            if st_lbl or st_desc:
                d_steps.append({"step": f"{s_i + 1:02d}", "label": st_lbl, "desc": st_desc})

    t_headers = [_clean_txt(h) for h in (raw_item.get("table_headers") or []) if _clean_txt(h)][:4]
    t_rows = []
    for rw in (raw_item.get("table_rows") or [])[:6]:
        if isinstance(rw, list):
            cells = [str(c or "").strip() for c in rw][:4]
            if any(cells) and (allow_econ or not ECON_LEAK_RE.search(" ".join(cells))):
                t_rows.append(cells)

    formula_txt = _clean_txt(raw_item.get("formula"))
    formula_desc = _clean_txt(raw_item.get("formula_desc"))

    return {
        "layout": layout,
        "badge": str(raw_item.get("badge") or f"{idx + 1:02d}-SLAYD").strip(),
        "title": _clean_txt(raw_item.get("title")) or f"Slayd #{idx + 1}",
        "subtitle": _clean_txt(raw_item.get("subtitle")),
        "bullets": bullets,
        "formula": formula_txt,
        "formula_desc": formula_desc,
        "table_headers": t_headers,
        "table_rows": t_rows,
        "highlight": _clean_txt(raw_item.get("highlight")),
        "stats": stats,
        "diagram_steps": d_steps,
        "image_query": str(raw_item.get("image_query") or "").strip(),
        "notes": _clean_txt(raw_item.get("notes")),
    }


class Room:
    def __init__(self, code, pin, preset_id="econ", teams=None):
        self.code = code
        self.pin = pin
        self.created_at = time.time()
        self.updated_at = time.time()
        self.teams = list(teams) if teams and len(teams) == 4 else ["1-jamoa", "2-jamoa", "3-jamoa", "4-jamoa"]
        self.scores = [0, 0, 0, 0]
        self.mode = "jeopardy"
        self.players = {}
        self.ai_busy = False
        self.ai_status = ""
        self.ai_error = ""
        self.ai_note = ""

        self.used = [False] * 25
        self.cur = None
        self.revealed = False
        self.answers = {}
        self.text_answers = {}
        self.ai_grades = {}

        self.mil = None
        self.auc = None
        self.bomb = None
        self.kahoot = None
        self.slides = None
        self.classic_test = None

        self.topic_title = ""
        self.cats = []
        self.questions = []
        self.load_preset(preset_id)

    def touch(self):
        self.updated_at = time.time()

    def clear_subgames(self):
        self.mil = None
        self.auc = None
        self.bomb = None
        self.kahoot = None
        self.classic_test = None

    def load_preset(self, preset_id):
        pack = PRESET_DATA.get(preset_id) or PRESET_DATA["econ"]
        self.topic_title = pack["title"]
        self.questions = copy.deepcopy(pack["questions"])
        self.cats = [self.questions[c * 5]["cat"] for c in range(5)]
        self.used = [False] * 25
        self.cur = None
        self.revealed = False
        self.answers = {}
        self.text_answers = {}
        self.ai_grades = {}
        self.ai_note = ""
        self.clear_subgames()

    def build_slides_from_current_questions(self, theme="royal"):
        allow_ec = is_economics_topic(self.topic_title)
        items = [
            normalize_slide_item({
                "layout": "cover",
                "badge": "01 / REJA",
                "title": self.topic_title or "Interaktiv Ma'ruza",
                "subtitle": f"REJA: {len(self.cats)} ta asosiy yo‘nalish • {len(self.questions)} ta tahliliy savol",
                "bullets": self.cats[:5],
                "highlight": "Jeo Quiz Pro — Akademik Infografik Taqdimot",
                "image_query": self.topic_title or "Education science",
                "notes": "Kirish qismi: mavzuning rejasi bilan tanishtiring.",
            }, 0, allow_econ=allow_ec)
        ]
        layouts = ["split_image", "formula_model", "table_matrix", "diagram_flow", "comparison"]
        for c_idx, cat in enumerate(self.cats):
            cat_qs = [q for q in self.questions if q["cat"] == cat][:4]
            bullets = []
            d_steps = []
            t_rows = []
            for idx_q, q in enumerate(cat_qs):
                ans_txt = q["opts"][q["c"]] if (q.get("opts") and q.get("c") is not None) else q.get("ans", "")
                exp_txt = f" — {q['exp']}" if q.get("exp") else ""
                bullets.append(f"{q['q']} → {ans_txt}{exp_txt}")
                d_steps.append({"label": ans_txt[:36], "desc": q["q"][:85]})
                t_rows.append([f"0{idx_q+1}", ans_txt[:34], (q.get("exp") or q["q"])[:55]])
            key_exp = cat_qs[0].get("exp", "") if cat_qs else ""
            items.append(
                normalize_slide_item({
                    "layout": layouts[c_idx % len(layouts)],
                    "badge": f"{c_idx + 2:02d} / BO‘LIM",
                    "title": cat,
                    "subtitle": f"{cat} yo‘nalishi bo‘yicha asosiy qoidalar va tahlil",
                    "bullets": bullets,
                    "formula": f"{cat}: Asosiy Qoida va Tizim",
                    "formula_desc": key_exp or f"{cat} doirasidagi asosiy tushunchalar o‘zaro bog‘liq.",
                    "table_headers": ["№", "Asosiy tushuncha", "Izoh va ahamiyati"],
                    "table_rows": t_rows,
                    "diagram_steps": d_steps,
                    "image_query": f"{cat} {self.topic_title}",
                    "highlight": key_exp or f"{cat} bo‘yicha muhim xulosalar",
                    "notes": f"{cat} bo‘limidagi asosiy faktlarni tushuntiring.",
                }, c_idx + 1, allow_econ=allow_ec)
            )
        items.append(
            normalize_slide_item({
                "layout": "summary",
                "badge": f"{len(items) + 1:02d} / XULOSA",
                "title": "Asosiy Xulosalar va Mustahkamlash",
                "subtitle": f"«{self.topic_title}» mavzusi yakuni",
                "bullets": [
                    "Barcha rejadagi asosiy yo‘nalishlar tizimli ko‘rib chiqildi",
                    "Nazariy qoidalar jadval va sxemalar asosida mustahkamlandi",
                    "Bilimlarni tekshirish uchun Oddiy Test rejimiga o‘tish mumkin",
                    "Savol va takliflar uchun ochiq muhokama",
                ],
                "highlight": "E’tiboringiz uchun rahmat!",
                "notes": "Mavzuni yakunlang.",
            }, len(items), allow_econ=allow_ec)
        )
        self.slides = {
            "title": self.topic_title or "Taqdimot",
            "theme": theme,
            "cur_idx": 0,
            "items": items,
        }

    def public_q(self, q, include_secret=False):
        if not q:
            return None
        d = {
            "cat": q["cat"],
            "pts": q["pts"],
            "q": q["q"],
            "opts": list(q.get("opts") or []),
            "exp": q.get("exp", "") if include_secret else "",
            "ans": q.get("ans", "") if include_secret else "",
        }
        if include_secret:
            d["c"] = q.get("c")
        return d

    def get_mc_pool(self):
        pool = [copy.deepcopy(q) for q in self.questions if len(q.get("opts") or []) == 4 and q.get("c") is not None]
        if not pool:
            pool = copy.deepcopy(PRESET_DATA["econ"]["questions"])
        random.shuffle(pool)
        return pool

    def tick_timers(self):
        now = time.time()
        if self.bomb and self.bomb["status"] == "playing":
            rem = max(0, int(round(self.bomb["deadline"] - now)))
            self.bomb["time_left"] = rem
            if rem <= 0:
                h = self.bomb["holder"]
                self.bomb["lives"][h] = max(0, self.bomb["lives"][h] - 1)
                self.bomb["status"] = "boom"
                self.bomb["last_msg"] = f"💥 VAQT TUGADI! {self.teams[h]} 1 ta jon yo‘qotdi!"

        if self.kahoot and self.kahoot["phase"] == "question":
            rem = max(0, int(round(self.kahoot["deadline"] - now)))
            self.kahoot["time_left"] = rem
            if rem <= 0:
                self.kahoot_do_reveal()

    def kahoot_do_reveal(self):
        k = self.kahoot
        if not k:
            return
        k["phase"] = "reveal"
        k["time_left"] = 0
        for name, rec in k["records"].items():
            res = k["round_results"].get(name)
            if not res or not res["ok"]:
                rec["streak"] = 0

    def serialize(self, is_admin=False):
        self.tick_timers()
        cur_q = self.questions[self.cur] if (self.cur is not None and 0 <= self.cur < len(self.questions)) else None
        inc_sec = is_admin or self.revealed

        mil_out = None
        if self.mil:
            m = self.mil
            mq = m["pool"][m["step"]]
            votes = m["votes"]
            vc = [sum(1 for v in votes.values() if v == i) for i in range(4)]
            mil_out = {
                "active": m["active"], "player": m["player"], "team": m["team"],
                "step": m["step"], "total_steps": len(MIL_PRIZES), "prizes": MIL_PRIZES,
                "safe_steps": MIL_SAFES, "won": m["won"], "status": m["status"],
                "revealed": m["revealed"], "selected": m["selected"],
                "hidden_opts": m["hidden_opts"], "lifelines": m["lifelines"],
                "audience_open": m["audience_open"], "vote_counts": vc,
                "vote_total": len(votes), "ai_hint": m["ai_hint"], "credited": m["credited"],
                "question": self.public_q(mq, include_secret=(is_admin or m["revealed"])),
            }

        auc_out = None
        if self.auc:
            a = self.auc
            aq = a["pool"][a["round"] - 1]
            auc_out = {
                "round": a["round"], "total_rounds": a["total_rounds"], "cat": aq["cat"],
                "phase": a["phase"], "bank": a["bank"], "bets": a["bets"],
                "answers": a["answers"] if (is_admin or a["phase"] == "revealed") else {},
                "answered_teams": [int(k) for k in a["answers"].keys()], "deltas": a["deltas"],
                "question": self.public_q(aq, include_secret=(is_admin or a["phase"] == "revealed")) if a["phase"] != "betting" else None,
            }

        bomb_out = None
        if self.bomb:
            b = self.bomb
            bomb_out = {
                "holder": b["holder"], "lives": b["lives"], "time_left": b["time_left"],
                "status": b["status"], "last_choice": b["last_choice"], "last_msg": b["last_msg"],
                "question": self.public_q(b["cur_q"], include_secret=(is_admin or b["status"] != "playing")),
            }

        kahoot_out = None
        if self.kahoot:
            k = self.kahoot
            lb = sorted(
                [{"name": nm, "team": rc["team"], "pts": rc["pts"], "streak": rc["streak"], "correct": rc["correct"]} for nm, rc in k["records"].items()],
                key=lambda x: (-x["pts"], -x["correct"], x["name"]),
            )
            vc = [sum(1 for r in k["round_results"].values() if r["choice"] == i) for i in range(4)]
            kahoot_out = {
                "phase": k["phase"], "q_num": k["q_num"], "total_q": len(k["pool"]),
                "time_left": k["time_left"],
                "question": self.public_q(k["cur_q"], include_secret=(is_admin or k["phase"] == "reveal")) if k["cur_q"] else None,
                "answered_count": len(k["round_results"]),
                "answered_names": list(k["round_results"].keys()),
                "vote_counts": vc, "round_results": k["round_results"],
                "leaderboard": lb, "team_pts": k["team_pts"],
            }

        slides_out = None
        if self.slides:
            sl = self.slides
            items_out = []
            for it in sl["items"]:
                d = dict(it)
                if not is_admin:
                    d["notes"] = ""
                items_out.append(d)
            slides_out = {
                "title": sl["title"],
                "theme": sl["theme"],
                "cur_idx": sl["cur_idx"],
                "total": len(items_out),
                "items": items_out,
            }

        ctest_out = None
        if self.classic_test:
            ct = self.classic_test
            pool_out = []
            for idx, q in enumerate(ct["pool"]):
                qd = {
                    "idx": idx,
                    "cat": q["cat"],
                    "pts": q["pts"],
                    "q": q["q"],
                    "opts": list(q["opts"]),
                }
                if is_admin:
                    qd["c"] = q["c"]
                    qd["exp"] = q.get("exp", "")
                pool_out.append(qd)

            subs_summary = sorted(
                [
                    {
                        "name": nm,
                        "team": sb["team"],
                        "correct": sb["correct"],
                        "total": sb["total"],
                        "percent": sb["percent"],
                        "score": sb["score"],
                        "duration_sec": sb["duration_sec"],
                    }
                    for nm, sb in ct["submissions"].items()
                ],
                key=lambda x: (-x["percent"], -x["score"], x["duration_sec"]),
            )
            ctest_out = {
                "active": ct["active"],
                "title": ct["title"],
                "time_limit": ct["time_limit"],
                "show_explanations": ct["show_explanations"],
                "total_q": len(pool_out),
                "pool": pool_out,
                "submissions_list": subs_summary,
                "submissions": ct["submissions"],
                "team_pts": ct["team_pts"],
            }

        active_ais = get_active_ai_list()
        return {
            "room": self.code, "topic_title": self.topic_title, "presets": PRESETS_META,
            "ai_ready": bool(active_ais), "ai_providers": active_ais,
            "ai_busy": self.ai_busy, "ai_status": self.ai_status,
            "ai_error": self.ai_error, "ai_note": self.ai_note,
            "tg_ready": bool(TELEGRAM_BOT_TOKEN), "tg_bot": TG_BOT_INFO,
            "mode": self.mode, "teams": self.teams, "scores": self.scores,
            "cats": self.cats, "used": self.used, "cur": self.cur, "revealed": self.revealed,
            "question": self.public_q(cur_q, include_secret=inc_sec),
            "answers": self.answers, "text_answers": self.text_answers, "ai_grades": self.ai_grades,
            "players": [{"name": n, "team": t} for n, t in self.players.items()],
            "mil": mil_out, "auc": auc_out, "bomb": bomb_out, "kahoot": kahoot_out,
            "slides": slides_out, "classic_test": ctest_out,
        }


LOCK = threading.Lock()
ROOMS = {}
DEFAULT_ROOM = Room("0000", DEFAULT_ADMIN_PIN, "econ")
ROOMS["0000"] = DEFAULT_ROOM


def cleanup_old_rooms():
    now = time.time()
    stale = [k for k, r in ROOMS.items() if k != "0000" and (now - r.updated_at) > 6 * 3600]
    for k in stale:
        del ROOMS[k]


def get_room(code):
    c = str(code or "").strip()
    if not c or c == "0000":
        return DEFAULT_ROOM
    return ROOMS.get(c)


def generate_room_code():
    for _ in range(500):
        c = f"{random.randint(1000, 9999)}"
        if c not in ROOMS:
            return c
    return f"{random.randint(10000, 99999)}"


def run_ai_board_worker(room, topic, level, file_part=None, extra_text="", preferred=None):
    try:
        allow_econ = is_economics_topic(topic)
        domain_rule = (
            "Mavzu iqtisodiyotga oid: zarur o‘rinlarda iqtisodiy tushunchalar va formulalardan foydalan."
            if allow_econ
            else f"MUHIM: '{topic}' mavzusi iqtisodiyotga oid EMAS! Savol va izohlarda iqtisodiy formulalar (UX=DX+O'X, Pc=s+v, Sv=C+v+m, F_ich, R', VP va h.k.) umuman ishlatilmasin."
        )
        base_prompt = (
            f"O‘zbek tilida '{topic}' mavzusida ({level} uchun) Jeopardy va viktorina o‘yinlariga mos "
            f"5 ta bo‘lim va har bir bo‘limda 5 tadan — jami 25 ta test savol tuz.\n"
            f"{domain_rule}\n"
            f"Qat'iy JSON formatida javob ber:\n"
            f'{{"cats": ["Bo‘lim 1", "Bo‘lim 2", "Bo‘lim 3", "Bo‘lim 4", "Bo‘lim 5"], '
            f'"questions": [{{"cat": "Bo‘lim 1", "q": "Savol?", "opts": ["A", "B", "C", "D"], "c": 0, "exp": "Qisqa izoh"}} ...]}}\n'
            f"Har bir savolda 4 ta variant ('opts') va to‘g‘ri javob indeksi ('c': 0, 1, 2 yoki 3) aniq bo‘lsin."
        )
        if extra_text:
            base_prompt += f"\n\nManba matni asosida savollar tuz:\n{extra_text[:18000]}"

        with LOCK:
            room.ai_status = "AI 25 ta savol va 5 ta bo‘lim tuzmoqda..."

        raw = call_gemini(base_prompt, file_part=file_part, json_mode=True, preferred=preferred)
        data = extract_json_block(raw)

        raw_cats = [str(c).strip() for c in (data.get("cats") or []) if str(c).strip()]
        raw_qs = data.get("questions") or []

        if len(raw_cats) < 5:
            seen = []
            for q in raw_qs:
                ct = str(q.get("cat") or "").strip()
                if ct and ct not in seen:
                    seen.append(ct)
            for ct in seen:
                if ct not in raw_cats:
                    raw_cats.append(ct)
            while len(raw_cats) < 5:
                raw_cats.append(f"{len(raw_cats) + 1}-bo‘lim")
        cats = raw_cats[:5]

        by_cat = {c: [] for c in cats}
        leftover = []
        for q in raw_qs:
            if not isinstance(q, dict):
                continue
            q_txt = str(q.get("q") or "").strip()
            opts = [str(o).strip() for o in (q.get("opts") or []) if str(o).strip()]
            if not q_txt or len(opts) < 2:
                continue
            while len(opts) < 4:
                opts.append(f"Variant {len(opts) + 1}")
            opts = opts[:4]
            try:
                c_idx = int(q.get("c", 0))
            except Exception:
                c_idx = 0
            if c_idx < 0 or c_idx > 3:
                c_idx = 0
            item = {
                "cat": str(q.get("cat") or "").strip(),
                "q": q_txt,
                "opts": opts,
                "c": c_idx,
                "ans": opts[c_idx],
                "exp": str(q.get("exp") or "").strip(),
            }
            if item["cat"] in by_cat and len(by_cat[item["cat"]]) < 5:
                by_cat[item["cat"]].append(item)
            else:
                leftover.append(item)

        final_questions = []
        for c in cats:
            bucket = by_cat[c]
            while len(bucket) < 5 and leftover:
                extra_item = leftover.pop(0)
                extra_item["cat"] = c
                bucket.append(extra_item)
            while len(bucket) < 5:
                n = len(bucket) + 1
                bucket.append({
                    "cat": c,
                    "q": f"{topic}: {c} yo‘nalishi bo‘yicha {n}-savol?",
                    "opts": ["To‘g‘ri ilmiy yondashuv", "Noto‘g‘ri talqin", "Qisman bog‘liq", "Aloqasiz tushuncha"],
                    "c": 0,
                    "ans": "To‘g‘ri ilmiy yondashuv",
                    "exp": f"{c} bo‘yicha asosiy nazariy qoida.",
                })
            for r_idx, q_item in enumerate(bucket[:5]):
                q_item["cat"] = c
                q_item["pts"] = (r_idx + 1) * 100
                final_questions.append(q_item)

        with LOCK:
            room.topic_title = topic or "AI Viktorina"
            room.cats = cats
            room.questions = final_questions
            room.used = [False] * 25
            room.cur = None
            room.revealed = False
            room.answers = {}
            room.text_answers = {}
            room.ai_grades = {}
            room.clear_subgames()
            room.ai_busy = False
            room.ai_status = ""
            room.ai_error = ""
            room.ai_note = f"✅ «{room.topic_title}» bo‘yicha 25 ta savol tayyor!"
            room.touch()
    except Exception as ex:
        with LOCK:
            room.ai_busy = False
            room.ai_status = ""
            room.ai_error = str(ex)
            room.touch()


def run_ai_slides_worker(room, topic, level, slide_count=10, theme="royal", file_part=None, extra_text="", preferred=None):
    try:
        count = max(5, min(16, int(slide_count or 10)))
        allow_econ = is_economics_topic(topic)

        if allow_econ:
            domain_instruction = (
                "MAVZU IQTISODIYOT/MOLIYA/BIZNESGA OID:\n"
                "- Akademik ma'ruza slaydlaridek chuqur, tizimli va formulalar bilan boyitilgan holda tuz.\n"
                "- Kerakli slaydlarda 'formula' va 'formula_desc' maydonlarini aniq iqtisodiy formulalar bilan to‘ldir "
                "(masalan: xarajatlar, tannarx, foyda massasi va normasi, nominal/real ish haqi yoki mavzuga mos formulalar).\n"
                "- Har bir bo‘limda ta'rif, tarkibiy qismlar, omillar, jadval va xulosa shiorini ber."
            )
            layout_hint = (
                "Slayd turlari ('layout') xilma-xil almashib kelsin: "
                "1-slayd albatta 'cover' (MAVZU va REJA), o‘rta slaydlar 'split_image', 'formula_model', 'table_matrix', "
                "'diagram_flow', 'comparison', 'stats_chart', oxirgi slayd albatta 'summary'."
            )
        else:
            domain_instruction = (
                f"QAT'IY CHEKLOV — '{topic}' MAVZUSI IQTISODIYOTGA OID EMAS:\n"
                "- Hech qanday iqtisodiy formula, belgi yoki atama (masalan: UX = DX + O'X, Pc = s + v, Sv = C + v + m, "
                "F_ich = Nu - T, R' = R / W, VP = VH / R, tannarx, ulgurji narx, avanslangan mablag', rentabellik, "
                "foyda normasi, ish haqi tarif setkasi va h.k.) MUTLAQO ISHLATILMASIN!\n"
                "- Barcha matnlar, ta'riflar, jadvallar, bosqichlar va sxemalar faqat '{topic}' fanining o‘z mazmunidan tuzilsin.\n"
                "- Agar '{topic}' fanida haqiqiy ilmiy/matematik formula bo‘lsa (masalan fizika, kimyo, matematika), "
                "faqat o‘sha fanning o‘z formulasini yoz. Agar mavzu gumanitar yoki formulasi yo‘q soha bo‘lsa "
                "(tarix, adabiyot, geografiya, biologiya, til va h.k.), 'formula_model' o‘rniga 'diagram_flow', "
                "'comparison', 'table_matrix' yoki 'split_image' ishlat va 'formula' maydonini bo‘sh (\"\") qoldir!"
            )
            layout_hint = (
                "Slayd turlari ('layout') akademik va infografik tarzda almashib kelsin: "
                "1-slayd albatta 'cover' (MAVZU va REJA), o‘rta slaydlar 'split_image', 'diagram_flow', 'table_matrix', "
                "'comparison', 'stats_chart' (va faqat mavzuda haqiqiy formula bo‘lsagina 'formula_model'), "
                "oxirgi slayd albatta 'summary'."
            )

        prompt = (
            f"O‘zbek tilida '{topic}' mavzusida ({level} darajasi uchun) {count} ta yuqori sifatli, "
            f"akademik-infografik taqdimot slaydlarini tuz.\n"
            f"{domain_instruction}\n"
            f"{layout_hint}\n\n"
            f"Har bir slayd tuzilmasi (namunaviy akademik taqdimot uslubida):\n"
            f"- 1-slayd ('cover'): 'title' = MAVZU nomi, 'subtitle' = 'REJA:' va qisqa tavsif, 'bullets' = 4-5 ta reja bandi, 'highlight' = mavzu shiori.\n"
            f"- Ichki slaydlar: aniq sarlavha ('title'), qisqa ta'rif ('subtitle'), 3-5 ta lo‘nda tahliliy band ('bullets'), "
            f"taqqoslash/tasnif jadvali ('table_headers' + 'table_rows'), 3-4 bosqichli jarayon sxemasi ('diagram_steps'), "
            f"ko‘rsatkichlar ('stats'), ingliz tilida rasm qidirish kalit so‘zi ('image_query') va pastki xulosa shiori ('highlight').\n"
            f"- Oxirgi slayd ('summary'): 'Asosiy xulosalar' va yakuniy shior.\n\n"
            f"Faqat quyidagi JSON formatida javob qaytar:\n"
            f'{{"title": "{topic}", "slides": ['
            f'{{"layout": "cover", "badge": "01 / REJA", "title": "{topic}", "subtitle": "REJA: Asosiy yo‘nalishlar", '
            f'"bullets": ["1-reja", "2-reja", "3-reja", "4-reja"], "formula": "", "formula_desc": "", '
            f'"table_headers": [], "table_rows": [], '
            f'"diagram_steps": [{{"label": "1-bosqich", "desc": "Qisqa izoh"}}], '
            f'"stats": [{{"label": "Ko‘rsatkich", "value": "85%", "pct": 85}}], '
            f'"highlight": "Xulosa shiori!", "image_query": "english keywords for topic", "notes": "Ma’ruzachi izohi"}}'
            f"]}}"
        )
        if extra_text:
            prompt += f"\n\nQuyidagi yuklangan hujjat matni asosida slaydlar tayyorla:\n{extra_text[:20000]}"

        with LOCK:
            room.ai_status = f"AI «{topic}» mavzusida {count} ta Pro Slayd yaratmoqda..."

        raw = call_gemini(prompt, file_part=file_part, json_mode=True, preferred=preferred)
        data = extract_json_block(raw)
        raw_slides = data.get("slides") or data.get("items") or []
        if not raw_slides:
            raise RuntimeError("AI slaydlar ro‘yxatini bo‘sh qaytardi.")

        items = []
        for idx, rs in enumerate(raw_slides[:16]):
            if not isinstance(rs, dict):
                continue
            norm = normalize_slide_item(rs, idx, allow_econ=allow_econ)
            if not allow_econ:
                if ECON_LEAK_RE.search(norm["formula"]) or ECON_LEAK_RE.search(norm["formula_desc"]):
                    norm["formula"] = ""
                    norm["formula_desc"] = ""
                if norm["layout"] == "formula_model" and not norm["formula"]:
                    norm["layout"] = "diagram_flow" if norm["diagram_steps"] else "split_image"
            items.append(norm)

        if not items:
            raise RuntimeError("Slaydlarni formatlashda xatolik yuz berdi.")

        items[0]["layout"] = "cover"
        if len(items) > 1 and items[-1]["layout"] not in ("summary", "quote"):
            items[-1]["layout"] = "summary"

        with LOCK:
            room.topic_title = str(data.get("title") or topic).strip()
            room.slides = {
                "title": room.topic_title,
                "theme": theme or "royal",
                "cur_idx": 0,
                "items": items,
            }
            room.mode = "slides"
            room.ai_busy = False
            room.ai_status = ""
            room.ai_error = ""
            room.ai_note = f"✅ «{room.topic_title}» bo‘yicha {len(items)} ta Pro Slayd tayyor!"
            room.touch()
    except Exception as ex:
        with LOCK:
            room.ai_busy = False
            room.ai_status = ""
            room.ai_error = str(ex)
            room.touch()


def run_ai_grade_worker(room):
    try:
        with LOCK:
            if room.cur is None or not (0 <= room.cur < len(room.questions)):
                return
            q = copy.deepcopy(room.questions[room.cur])
            t_ans = copy.deepcopy(room.text_answers)
            teams = list(room.teams)

        if not t_ans:
            return

        correct_ref = q["opts"][q["c"]] if (q.get("opts") and q.get("c") is not None) else q.get("ans", "")
        entries = []
        for k, val in t_ans.items():
            try:
                t_idx = int(k)
                t_name = teams[t_idx] if 0 <= t_idx < len(teams) else f"{t_idx+1}-jamoa"
            except Exception:
                t_name = str(k)
            entries.append(f"- ID={k} ({t_name}): {val}")

        prompt = (
            f"Savol: {q['q']}\n"
            f"To‘g‘ri javob namunasi: {correct_ref}\n"
            f"Izoh: {q.get('exp', '')}\n\n"
            f"Jamoalar yozgan javoblar:\n" + "\n".join(entries) + "\n\n"
            f"Har bir jamoa javobini 0 dan 100 gacha ball bilan bahola va qisqa o‘zbekcha izoh yoz.\n"
            f'Faqat JSON qaytar: {{"grades": {{"0": {{"score": 100, "ok": true, "comment": "To‘liq to‘g‘ri"}}}}}}'
        )
        raw = call_gemini(prompt, json_mode=True)
        parsed = extract_json_block(raw)
        grades = parsed.get("grades") or {}
        with LOCK:
            room.ai_grades = grades
            room.touch()
    except Exception as ex:
        with LOCK:
            room.ai_error = f"AI baholash xatosi: {ex}"


def build_pptx_bytes(slides_data):
    if not slides_data or not slides_data.get("items"):
        raise RuntimeError("Eksport qilish uchun slaydlar mavjud emas.")

    theme_name = str(slides_data.get("theme") or "royal").lower()
    palettes = {
        "royal": {"bg": "F4F7FC", "primary": "1E3A8A", "accent": "2563EB", "card": "FFFFFF", "text": "0F172A", "muted": "475569", "banner": "DBEAFE"},
        "emerald": {"bg": "F0FDF4", "primary": "065F46", "accent": "059669", "card": "FFFFFF", "text": "064E3B", "muted": "374151", "banner": "D1FAE5"},
        "crimson": {"bg": "FEF2F2", "primary": "991B1B", "accent": "DC2626", "card": "FFFFFF", "text": "1F2937", "muted": "4B5563", "banner": "FEE2E2"},
        "amber": {"bg": "FFFBEB", "primary": "92400E", "accent": "D97706", "card": "FFFFFF", "text": "1F2937", "muted": "4B5563", "banner": "FEF3C7"},
        "dark": {"bg": "0F172A", "primary": "38BDF8", "accent": "6366F1", "card": "1E293B", "text": "F8FAFC", "muted": "CBD5E1", "banner": "1E293B"},
    }
    pal = palettes.get(theme_name, palettes["royal"])
    items = slides_data["items"]

    images_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        fut_to_idx = {}
        for idx, it in enumerate(items):
            q_img = it.get("image_query") or it.get("title")
            if q_img and idx < 12:
                fut_to_idx[pool.submit(fetch_topic_image_bytes, q_img)] = idx
        for fut in concurrent.futures.as_completed(fut_to_idx, timeout=14):
            idx = fut_to_idx[fut]
            try:
                ibytes, ext = fut.result()
                if ibytes and ext:
                    images_map[idx] = (ibytes, ext)
            except Exception:
                pass

    def _shape_xml(sid, name, x, y, cx, cy, fill_hex, border_hex=None, text_runs=None, align="l", anchor="t"):
        border_xml = (
            f'<a:ln w="12700"><a:solidFill><a:srgbClr val="{border_hex}"/></a:solidFill></a:ln>'
            if border_hex
            else "<a:ln><a:noFill/></a:ln>"
        )
        paras_xml = ""
        if text_runs:
            for txt, sz, bold, col_hex in text_runs:
                b_attr = ' b="1"' if bold else ""
                paras_xml += (
                    f'<a:p><a:pPr algn="{align}"/>'
                    f'<a:r><a:rPr lang="uz-UZ" sz="{sz}"{b_attr} dirty="0">'
                    f'<a:solidFill><a:srgbClr val="{col_hex}"/></a:solidFill>'
                    f'<a:latin typeface="Calibri"/>'
                    f'</a:rPr><a:t>{xml_esc(str(txt))}</a:t></a:r></a:p>'
                )
        else:
            paras_xml = "<a:p/>"

        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{xml_esc(name)}"/>'
            f"<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 3500"/></a:avLst></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill_hex}"/></a:solidFill>{border_xml}</p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="140000" tIns="100000" rIns="140000" bIns="100000" anchor="{anchor}"/>'
            f"<a:lstStyle/>{paras_xml}</p:txBody></p:sp>"
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        slide_overrides = []
        sld_id_entries = []
        pres_rels = [
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>',
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>',
        ]
        media_exts = set()

        for idx, it in enumerate(items):
            s_num = idx + 1
            sid = 2
            shapes = []

            # Top accent bar
            shapes.append(_shape_xml(sid, "TopBar", 0, 0, 12192000, 110000, pal["accent"]))
            sid += 1

            # Badge + Slide number
            badge_txt = it.get("badge") or f"{s_num:02d}-SLAYD"
            shapes.append(_shape_xml(
                sid, "Badge", 450000, 240000, 2600000, 380000, pal["accent"],
                text_runs=[(badge_txt, 1300, True, "FFFFFF")], align="ctr", anchor="ctr"
            ))
            sid += 1

            shapes.append(_shape_xml(
                sid, "PageNum", 11100000, 240000, 650000, 380000, pal["banner"],
                text_runs=[(f"{s_num}/{len(items)}", 1300, True, pal["primary"])], align="ctr", anchor="ctr"
            ))
            sid += 1

            # Title & Subtitle
            title_runs = [(it.get("title") or f"Slayd {s_num}", 2400, True, pal["primary"])]
            if it.get("subtitle"):
                title_runs.append((it["subtitle"], 1400, False, pal["muted"]))
            shapes.append(_shape_xml(
                sid, "HeaderBox", 450000, 680000, 11292000, 1150000, pal["card"], pal["banner"],
                text_runs=title_runs
            ))
            sid += 1

            has_img = idx in images_map
            left_w = 6850000 if has_img else 11292000
            body_runs = []

            if it.get("formula"):
                body_runs.append((f"FORMULA: {it['formula']}", 1800, True, pal["accent"]))
                if it.get("formula_desc"):
                    body_runs.append((it["formula_desc"], 1300, False, pal["muted"]))

            for b in (it.get("bullets") or [])[:5]:
                body_runs.append((f"✔  {b}", 1450, False, pal["text"]))

            for ds in (it.get("diagram_steps") or [])[:4]:
                body_runs.append((f"[{ds.get('step', '01')}] {ds.get('label', '')}: {ds.get('desc', '')}", 1350, True, pal["primary"]))

            if it.get("table_headers") and it.get("table_rows"):
                body_runs.append((" | ".join(it["table_headers"]), 1350, True, pal["accent"]))
                for rw in it["table_rows"][:5]:
                    body_runs.append((" — ".join(rw), 1300, False, pal["text"]))

            for st in (it.get("stats") or [])[:4]:
                body_runs.append((f"• {st.get('label', '')}: {st.get('value', '')}", 1400, True, pal["primary"]))

            if not body_runs:
                body_runs.append((it.get("subtitle") or it.get("title") or "", 1500, False, pal["text"]))

            shapes.append(_shape_xml(
                sid, "MainContent", 450000, 1950000, left_w, 3950000, pal["card"], pal["banner"],
                text_runs=body_runs
            ))
            sid += 1

            pic_xml = ""
            s_rels = [
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            ]
            if has_img:
                ibytes, ext = images_map[idx]
                media_exts.add(ext)
                img_fname = f"image{s_num}.{ext}"
                zf.writestr(f"ppt/media/{img_fname}", ibytes)
                s_rels.append(
                    f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/{img_fname}"/>'
                )
                pic_xml = (
                    f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="Picture {s_num}"/>'
                    f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
                    f'<p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
                    f'<p:spPr><a:xfrm><a:off x="7480000" y="1950000"/><a:ext cx="4262000" cy="3950000"/></a:xfrm>'
                    f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 3500"/></a:avLst></a:prstGeom></p:spPr></p:pic>'
                )
                sid += 1

            # Bottom slogan banner
            slogan = it.get("highlight") or slides_data.get("title") or "Jeo Quiz Pro"
            shapes.append(_shape_xml(
                sid, "FooterBanner", 450000, 6050000, 11292000, 540000, pal["banner"], pal["accent"],
                text_runs=[(f"★  {slogan}", 1450, True, pal["primary"])], align="ctr", anchor="ctr"
            ))

            slide_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f'<p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="{pal["bg"]}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
                f'<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                + "".join(shapes) + pic_xml +
                "</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{s_num}.xml", slide_xml)
            zf.writestr(
                f"ppt/slides/_rels/slide{s_num}.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(s_rels) + "</Relationships>"
            )
            slide_overrides.append(
                f'<Override PartName="/ppt/slides/slide{s_num}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            )
            r_id = f"rId{s_num + 2}"
            pres_rels.append(
                f'<Relationship Id="{r_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{s_num}.xml"/>'
            )
            sld_id_entries.append(f'<p:sldId id="{255 + s_num}" r:id="{r_id}"/>')

        img_defaults = ""
        if "png" in media_exts:
            img_defaults += '<Default Extension="png" ContentType="image/png"/>'
        if "jpg" in media_exts:
            img_defaults += '<Default Extension="jpg" ContentType="image/jpeg"/>'

        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{img_defaults}"
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            + "".join(slide_overrides) + "</Types>"
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            "</Relationships>"
        )
        zf.writestr(
            "ppt/presentation.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            f"<p:sldIdLst>{''.join(sld_id_entries)}</p:sldIdLst>"
            '<p:sldSz cx="12192000" cy="6858000" type="screen16x9"/>'
            '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
        )
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(pres_rels) + "</Relationships>"
        )
        zf.writestr(
            "ppt/slideMasters/slideMaster1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>'
        )
        zf.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
            "</Relationships>"
        )
        zf.writestr(
            "ppt/slideLayouts/slideLayout1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank">'
            '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            "</p:spTree></p:cSld></p:sldLayout>"
        )
        zf.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
            "</Relationships>"
        )
        zf.writestr(
            "ppt/theme/theme1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="JeoQuizTheme">'
            '<a:themeElements><a:clrScheme name="Jeo">'
            '<a:dk1><a:srgbClr val="0F172A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
            '<a:dk2><a:srgbClr val="1E293B"/></a:dk2><a:lt2><a:srgbClr val="F1F5F9"/></a:lt2>'
            '<a:accent1><a:srgbClr val="2563EB"/></a:accent1><a:accent2><a:srgbClr val="059669"/></a:accent2>'
            '<a:accent3><a:srgbClr val="D97706"/></a:accent3><a:accent4><a:srgbClr val="DC2626"/></a:accent4>'
            '<a:accent5><a:srgbClr val="7C3AED"/></a:accent5><a:accent6><a:srgbClr val="0891B2"/></a:accent6>'
            '<a:hlink><a:srgbClr val="2563EB"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink>'
            "</a:clrScheme>"
            '<a:fontScheme name="JeoFont"><a:majorFont><a:latin typeface="Calibri"/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/></a:minorFont></a:fontScheme>'
            '<a:fmtScheme name="JeoFmt"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
            '<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
            '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
            '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
            "</a:fmtScheme></a:themeElements></a:theme>"
        )
    return buf.getvalue()


def _tg_request(method, payload=None):
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def telegram_bot_worker():
    global TG_BOT_INFO
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        me = _tg_request("getMe")
        if me and me.get("ok"):
            TG_BOT_INFO = {"ok": True, "username": me["result"].get("username", ""), "error": ""}
    except Exception as ex:
        TG_BOT_INFO = {"ok": False, "username": "", "error": str(ex)}
        return

    offset = 0
    while True:
        try:
            upd = _tg_request("getUpdates", {"offset": offset, "timeout": 15})
            for item in (upd or {}).get("result") or []:
                offset = item["update_id"] + 1
                msg = item.get("message") or {}
                chat_id = (msg.get("chat") or {}).get("id")
                txt = str(msg.get("text") or "").strip()
                if not chat_id or not txt:
                    continue
                if txt.startswith("/start"):
                    reply = (
                        f"👋 Assalomu alaykum! <b>Jeo Quiz Pro</b> botiga xush kelibsiz.\n\n"
                        f"🎮 O‘yinga kirish: {APP_PUBLIC_URL}\n"
                        f"🛠 Admin panel: {APP_PUBLIC_URL}/admin\n"
                        f"🔑 Standart xona kodi: <code>0000</code>"
                    )
                    _tg_request("sendMessage", {"chat_id": chat_id, "text": reply, "parse_mode": "HTML"})
                elif txt.startswith("/room"):
                    with LOCK:
                        code = generate_room_code()
                        ROOMS[code] = Room(code, DEFAULT_ADMIN_PIN, "econ")
                    reply = (
                        f"✅ Yangi o‘yin xonasi ochildi!\n"
                        f"🔢 Xona kodi: <code>{code}</code>\n"
                        f"🔐 Admin PIN: <code>{DEFAULT_ADMIN_PIN}</code>\n"
                        f"🌐 Havola: {APP_PUBLIC_URL}/?room={code}"
                    )
                    _tg_request("sendMessage", {"chat_id": chat_id, "text": reply, "parse_mode": "HTML"})
        except Exception:
            time.sleep(5)


def _prepare_uploaded_file(body):
    b64 = str(body.get("file_b64") or body.get("b64") or "").strip()
    mime = str(body.get("file_mime") or body.get("mime") or "").strip()
    fname = str(body.get("file_name") or body.get("filename") or "").strip().lower()
    if not b64:
        return None, ""
    if "," in b64 and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    if fname.endswith(".docx") or "wordprocessingml" in mime:
        return None, extract_docx_text(b64)
    if fname.endswith(".txt") or mime.startswith("text/"):
        raw_txt = base64.b64decode(b64).decode("utf-8", errors="ignore")
        return None, raw_txt[:28000]
    if not mime:
        mime = "application/pdf" if fname.endswith(".pdf") else "image/jpeg"
    return {"mime": mime, "b64": b64}, ""


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class QuizHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _send_html_file(self, filename):
        fpath = os.path.join(BASE_DIR, filename)
        if not os.path.isfile(fpath):
            self._send_json({"ok": False, "error": f"{filename} topilmadi"}, 404)
            return
        with open(fpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_pptx(self, room):
        with LOCK:
            sl_copy = copy.deepcopy(room.slides)
        if not sl_copy:
            self._send_json({"ok": False, "error": "Avval slayd yarating"}, 400)
            return
        pptx_bytes = build_pptx_bytes(sl_copy)
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", sl_copy.get("title") or "JeoQuiz_Slides")[:40] or "Slides"
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}.pptx"')
        self.send_header("Content-Length", str(len(pptx_bytes)))
        self.end_headers()
        self.wfile.write(pptx_bytes)

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._send_html_file("index.html")
        if path in ("/admin", "/admin.html"):
            return self._send_html_file("admin.html")
        if path in ("/health", "/ping"):
            return self._send_json({"ok": True, "rooms": len(ROOMS)})

        room_code = (qs.get("room") or ["0000"])[0]
        is_admin = (qs.get("admin") or ["0"])[0] in ("1", "true", "yes")

        if path in ("/api/pptx", "/api/export_pptx", "/api/slides/pptx"):
            with LOCK:
                room = get_room(room_code)
            if not room:
                return self._send_json({"ok": False, "error": "Xona topilmadi"}, 404)
            try:
                return self._send_pptx(room)
            except Exception as ex:
                return self._send_json({"ok": False, "error": str(ex)}, 500)

        if path == "/api/state":
            with LOCK:
                room = get_room(room_code)
                if not room:
                    return self._send_json({"ok": False, "error": "Xona topilmadi"}, 404)
                return self._send_json({"ok": True, **room.serialize(is_admin=is_admin)})

        return self._send_json({"ok": False, "error": "Yo‘nalish topilmadi"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            body = json.loads(raw_body) if raw_body.strip() else {}
        except Exception:
            return self._send_json({"ok": False, "error": "Noto‘g‘ri JSON"}, 400)

        action = str(body.get("action") or "").strip()
        room_code = str(body.get("room") or "0000").strip()

        if path == "/api/create_room" or action == "create_room":
            with LOCK:
                cleanup_old_rooms()
                code = generate_room_code()
                pin = str(body.get("pin") or DEFAULT_ADMIN_PIN).strip() or DEFAULT_ADMIN_PIN
                preset = str(body.get("preset") or "econ").strip()
                teams = body.get("teams")
                rm = Room(code, pin, preset, teams=teams)
                ROOMS[code] = rm
                return self._send_json({"ok": True, "room": code, "pin": pin, **rm.serialize(is_admin=True)})

        if path in ("/api/pptx", "/api/export_pptx", "/api/slides/pptx") or action == "export_pptx":
            with LOCK:
                room = get_room(room_code)
            if not room:
                return self._send_json({"ok": False, "error": "Xona topilmadi"}, 404)
            try:
                return self._send_pptx(room)
            except Exception as ex:
                return self._send_json({"ok": False, "error": str(ex)}, 500)

        with LOCK:
            room = get_room(room_code)
            if not room:
                return self._send_json({"ok": False, "error": "Xona topilmadi"}, 404)

            if path == "/api/check_pin" or action == "check_pin":
                pin = str(body.get("pin") or "").strip()
                if pin != room.pin:
                    return self._send_json({"ok": False, "error": "Admin PIN kodi noto‘g‘ri!"}, 403)
                return self._send_json({"ok": True, **room.serialize(is_admin=True)})

            # Player join
            if path in ("/api/join", "/api/player/join") or action == "join":
                name = str(body.get("name") or "").strip()[:28]
                team = max(0, min(3, int(body.get("team", 0))))
                if not name:
                    return self._send_json({"ok": False, "error": "Ismingizni kiriting"}, 400)
                room.players[name] = team
                if room.kahoot and name not in room.kahoot["records"]:
                    room.kahoot["records"][name] = {"team": team, "pts": 0, "streak": 0, "correct": 0}
                room.touch()
                return self._send_json({"ok": True, **room.serialize(is_admin=False)})

            # AI Board generation
            if path in ("/api/ai_generate", "/api/generate") or action == "ai_generate":
                if room.ai_busy:
                    return self._send_json({"ok": False, "error": "AI hozir band, kuting..."}, 409)
                topic = str(body.get("topic") or "Umumiy bilimlar").strip()
                level = str(body.get("level") or "Talabalar").strip()
                preferred = body.get("provider")
                file_part, extra_text = _prepare_uploaded_file(body)
                room.ai_busy = True
                room.ai_error = ""
                room.ai_status = "AI ishga tushmoqda..."
                room.touch()
                threading.Thread(
                    target=run_ai_board_worker,
                    args=(room, topic, level, file_part, extra_text, preferred),
                    daemon=True,
                ).start()
                return self._send_json({"ok": True, **room.serialize(is_admin=True)})

            # AI Pro Slides generation
            if path in ("/api/ai_slides", "/api/slides/generate") or action == "ai_slides":
                if room.ai_busy:
                    return self._send_json({"ok": False, "error": "AI hozir band, kuting..."}, 409)
                topic = str(body.get("topic") or room.topic_title or "Taqdimot").strip()
                level = str(body.get("level") or "Talabalar").strip()
                slide_count = int(body.get("slide_count") or body.get("count") or 10)
                theme = str(body.get("theme") or "royal").strip()
                preferred = body.get("provider")
                file_part, extra_text = _prepare_uploaded_file(body)
                room.ai_busy = True
                room.ai_error = ""
                room.ai_status = "AI Pro Slaydlar tayyorlamoqda..."
                room.touch()
                threading.Thread(
                    target=run_ai_slides_worker,
                    args=(room, topic, level, slide_count, theme, file_part, extra_text, preferred),
                    daemon=True,
                ).start()
                return self._send_json({"ok": True, **room.serialize(is_admin=True)})

            # --- Game & Admin State Actions ---
            act = action or path.split("/")[-1]
            is_adm = bool(body.get("is_admin", True))

            if act == "set_mode":
                mode = str(body.get("mode") or "jeopardy").strip()
                room.mode = mode
                if mode == "slides" and not room.slides:
                    room.build_slides_from_current_questions()
                elif mode == "classic_test" and not room.classic_test:
                    pool = room.get_mc_pool()[:15]
                    room.classic_test = {
                        "active": True,
                        "title": room.topic_title or "Oddiy Test",
                        "time_limit": 600,
                        "show_explanations": True,
                        "pool": pool,
                        "submissions": {},
                        "team_pts": [0, 0, 0, 0],
                    }
                elif mode == "auction" and not room.auc:
                    pool = room.get_mc_pool()[:5]
                    start_bank = [s if s > 0 else 1000 for s in room.scores]
                    room.auc = {
                        "round": 1, "total_rounds": len(pool), "pool": pool,
                        "phase": "betting", "bank": start_bank, "bets": {}, "answers": {}, "deltas": {},
                    }
                elif mode == "bomb" and not room.bomb:
                    pool = room.get_mc_pool()
                    room.bomb = {
                        "holder": 0, "lives": [3, 3, 3, 3], "time_limit": 20,
                        "deadline": time.time() + 20, "time_left": 20, "status": "playing",
                        "last_choice": None, "last_msg": "💣 Bomba 1-jamoa qo‘lida!",
                        "pool": pool, "q_idx": 0, "cur_q": pool[0],
                    }
                elif mode == "kahoot" and not room.kahoot:
                    pool = room.get_mc_pool()[:10]
                    recs = {nm: {"team": tm, "pts": 0, "streak": 0, "correct": 0} for nm, tm in room.players.items()}
                    room.kahoot = {
                        "phase": "question", "q_num": 1, "pool": pool, "cur_q": pool[0],
                        "deadline": time.time() + 20, "time_left": 20,
                        "round_results": {}, "records": recs, "team_pts": [0, 0, 0, 0],
                    }

            elif act == "load_preset":
                room.load_preset(str(body.get("preset") or "econ"))

            elif act == "set_teams":
                tms = body.get("teams") or []
                if len(tms) == 4:
                    room.teams = [str(t).strip() or f"{i+1}-jamoa" for i, t in enumerate(tms)]

            elif act in ("set_score", "add_score"):
                t_idx = max(0, min(3, int(body.get("team", 0))))
                val = int(body.get("delta") if act == "add_score" else body.get("score", 0))
                if act == "add_score":
                    room.scores[t_idx] += val
                else:
                    room.scores[t_idx] = val

            elif act == "reset_scores":
                room.scores = [0, 0, 0, 0]

            elif act == "reset_board":
                room.used = [False] * 25
                room.cur = None
                room.revealed = False
                room.answers = {}
                room.text_answers = {}
                room.ai_grades = {}

            # Jeopardy controls
            elif act in ("select_q", "open_q"):
                idx = int(body.get("idx", 0))
                if 0 <= idx < len(room.questions):
                    room.cur = idx
                    room.revealed = False
                    room.answers = {}
                    room.text_answers = {}
                    room.ai_grades = {}

            elif act == "reveal_q":
                if room.cur is not None:
                    room.revealed = True
                    room.used[room.cur] = True

            elif act == "close_q":
                if room.cur is not None and body.get("mark_used", True):
                    room.used[room.cur] = True
                room.cur = None
                room.revealed = False

            elif act in ("answer", "player_answer"):
                t_key = str(body.get("team", 0))
                if "text" in body and str(body.get("text") or "").strip():
                    room.text_answers[t_key] = str(body["text"]).strip()[:400]
                elif "choice" in body and not room.revealed:
                    room.answers[t_key] = int(body["choice"])

            elif act == "award_team":
                t_idx = max(0, min(3, int(body.get("team", 0))))
                pts = int(body.get("pts", 0))
                room.scores[t_idx] += pts
                if room.cur is not None:
                    room.used[room.cur] = True
                    room.revealed = True

            elif act == "ai_grade":
                threading.Thread(target=run_ai_grade_worker, args=(room,), daemon=True).start()

            # Slides controls
            elif act == "slide_nav" and room.slides:
                total = len(room.slides["items"])
                direction = str(body.get("dir") or "next")
                cur = room.slides["cur_idx"]
                if direction == "next":
                    room.slides["cur_idx"] = min(total - 1, cur + 1)
                elif direction == "prev":
                    room.slides["cur_idx"] = max(0, cur - 1)
                elif direction == "goto":
                    room.slides["cur_idx"] = max(0, min(total - 1, int(body.get("idx", 0))))

            elif act == "slide_theme" and room.slides:
                room.slides["theme"] = str(body.get("theme") or "royal").strip()

            elif act == "slide_from_quiz":
                room.build_slides_from_current_questions(theme=str(body.get("theme") or "royal"))
                room.mode = "slides"

            elif act == "slide_update" and room.slides:
                idx = int(body.get("idx", room.slides["cur_idx"]))
                if 0 <= idx < len(room.slides["items"]):
                    it = room.slides["items"][idx]
                    for fld in ("title", "subtitle", "formula", "formula_desc", "highlight", "notes"):
                        if fld in body:
                            it[fld] = str(body[fld] or "").strip()
                    if "bullets" in body and isinstance(body["bullets"], list):
                        it["bullets"] = [str(x).strip() for x in body["bullets"] if str(x).strip()][:5]

            # Classic / Simple Test controls
            elif act == "ctest_start":
                q_cnt = max(5, min(25, int(body.get("count") or 15)))
                t_lim = max(60, int(body.get("time_limit") or 600))
                pool = room.get_mc_pool()[:q_cnt]
                room.classic_test = {
                    "active": True,
                    "title": str(body.get("title") or room.topic_title or "Oddiy Test").strip(),
                    "time_limit": t_lim,
                    "show_explanations": bool(body.get("show_explanations", True)),
                    "pool": pool,
                    "submissions": {},
                    "team_pts": [0, 0, 0, 0],
                }
                room.mode = "classic_test"

            elif act == "ctest_submit" and room.classic_test:
                ct = room.classic_test
                name = str(body.get("name") or "Ishtirokchi").strip()[:28]
                team = max(0, min(3, int(body.get("team", room.players.get(name, 0)))))
                ans_map = body.get("answers") or {}
                dur = max(1, int(body.get("duration_sec") or 1))
                correct = 0
                details = []
                for idx, q in enumerate(ct["pool"]):
                    picked = ans_map.get(str(idx)) if isinstance(ans_map, dict) else (ans_map[idx] if idx < len(ans_map) else None)
                    ok = (picked is not None and int(picked) == q["c"])
                    if ok:
                        correct += 1
                    details.append({"idx": idx, "picked": picked, "correct_idx": q["c"], "ok": ok, "exp": q.get("exp", "")})
                total = max(1, len(ct["pool"]))
                pct = round(correct * 100 / total)
                score = correct * 100
                ct["submissions"][name] = {
                    "team": team, "correct": correct, "total": total,
                    "percent": pct, "score": score, "duration_sec": dur, "details": details,
                }
                ct["team_pts"][team] += score
                room.scores[team] += score

            elif act == "ctest_stop" and room.classic_test:
                room.classic_test["active"] = False

            # Millionaire controls
            elif act == "mil_start":
                pool = room.get_mc_pool()[:15]
                while len(pool) < 15:
                    pool.extend(copy.deepcopy(PRESET_DATA["econ"]["questions"]))
                pool = pool[:15]
                room.mil = {
                    "active": True,
                    "player": str(body.get("player") or "Ishtirokchi").strip(),
                    "team": max(0, min(3, int(body.get("team", 0)))),
                    "step": 0, "pool": pool, "won": 0, "status": "playing",
                    "revealed": False, "selected": None, "hidden_opts": [],
                    "lifelines": {"5050": True, "audience": True, "ai": True},
                    "audience_open": False, "votes": {}, "ai_hint": "", "credited": False,
                }
                room.mode = "millionaire"

            elif act == "mil_select" and room.mil and not room.mil["revealed"]:
                room.mil["selected"] = int(body.get("choice", 0))

            elif act == "mil_reveal" and room.mil and room.mil["selected"] is not None:
                m = room.mil
                m["revealed"] = True
                q = m["pool"][m["step"]]
                if m["selected"] == q["c"]:
                    m["won"] = MIL_PRIZES[m["step"]]
                    if m["step"] == len(MIL_PRIZES) - 1:
                        m["status"] = "won"
                        m["active"] = False
                else:
                    safe = 0
                    for s_idx in MIL_SAFES:
                        if m["step"] > s_idx:
                            safe = MIL_PRIZES[s_idx]
                    m["won"] = safe
                    m["status"] = "lost"
                    m["active"] = False

            elif act == "mil_next" and room.mil and room.mil["revealed"] and room.mil["status"] == "playing":
                m = room.mil
                m["step"] = min(len(MIL_PRIZES) - 1, m["step"] + 1)
                m["selected"] = None
                m["revealed"] = False
                m["hidden_opts"] = []
                m["audience_open"] = False
                m["votes"] = {}
                m["ai_hint"] = ""

            elif act == "mil_walk" and room.mil:
                room.mil["status"] = "walked"
                room.mil["active"] = False

            elif act == "mil_lifeline" and room.mil:
                m = room.mil
                kind = str(body.get("kind") or "")
                q = m["pool"][m["step"]]
                if kind == "5050" and m["lifelines"]["5050"]:
                    m["lifelines"]["5050"] = False
                    wrongs = [i for i in range(4) if i != q["c"]]
                    random.shuffle(wrongs)
                    m["hidden_opts"] = wrongs[:2]
                elif kind == "audience" and m["lifelines"]["audience"]:
                    m["lifelines"]["audience"] = False
                    m["audience_open"] = True
                    m["votes"] = {}
                elif kind == "ai" and m["lifelines"]["ai"]:
                    m["lifelines"]["ai"] = False
                    m["ai_hint"] = q.get("exp") or f"To‘g‘ri javob {['A','B','C','D'][q['c']]} variantga yaqin."

            elif act == "mil_vote" and room.mil and room.mil["audience_open"]:
                voter = str(body.get("name") or random.randint(1, 99999))
                room.mil["votes"][voter] = max(0, min(3, int(body.get("choice", 0))))

            elif act == "mil_credit" and room.mil and not room.mil["credited"]:
                room.scores[room.mil["team"]] += room.mil["won"]
                room.mil["credited"] = True

            # Auction controls
            elif act == "auc_bet" and room.auc and room.auc["phase"] == "betting":
                t_idx = max(0, min(3, int(body.get("team", 0))))
                max_b = room.auc["bank"][t_idx]
                bet = max(0, min(max_b, int(body.get("bet", 0))))
                room.auc["bets"][str(t_idx)] = bet

            elif act == "auc_open_q" and room.auc:
                room.auc["phase"] = "answering"

            elif act == "auc_answer" and room.auc and room.auc["phase"] == "answering":
                t_idx = max(0, min(3, int(body.get("team", 0))))
                room.auc["answers"][str(t_idx)] = max(0, min(3, int(body.get("choice", 0))))

            elif act == "auc_reveal" and room.auc:
                a = room.auc
                q = a["pool"][a["round"] - 1]
                deltas = {}
                for t_idx in range(4):
                    tk = str(t_idx)
                    bet = int(a["bets"].get(tk, 0))
                    if tk in a["answers"] and bet > 0:
                        if int(a["answers"][tk]) == q["c"]:
                            a["bank"][t_idx] += bet
                            room.scores[t_idx] += bet
                            deltas[tk] = bet
                        else:
                            a["bank"][t_idx] = max(0, a["bank"][t_idx] - bet)
                            room.scores[t_idx] = max(0, room.scores[t_idx] - bet)
                            deltas[tk] = -bet
                    else:
                        deltas[tk] = 0
                a["deltas"] = deltas
                a["phase"] = "revealed"

            elif act == "auc_next" and room.auc:
                a = room.auc
                if a["round"] < a["total_rounds"]:
                    a["round"] += 1
                    a["phase"] = "betting"
                    a["bets"] = {}
                    a["answers"] = {}
                    a["deltas"] = {}
                else:
                    a["phase"] = "finished"

            # Chain Bomb controls
            elif act == "bomb_answer" and room.bomb and room.bomb["status"] == "playing":
                b = room.bomb
                choice = max(0, min(3, int(body.get("choice", 0))))
                b["last_choice"] = choice
                h = b["holder"]
                if choice == b["cur_q"]["c"]:
                    room.scores[h] += 100
                    alive = [i for i, lv in enumerate(b["lives"]) if lv > 0]
                    if len(alive) > 1:
                        nxt = alive[(alive.index(h) + 1) % len(alive)] if h in alive else alive[0]
                    else:
                        nxt = h
                    b["holder"] = nxt
                    b["q_idx"] = (b["q_idx"] + 1) % len(b["pool"])
                    b["cur_q"] = b["pool"][b["q_idx"]]
                    b["deadline"] = time.time() + b["time_limit"]
                    b["time_left"] = b["time_limit"]
                    b["last_msg"] = f"✅ To‘g‘ri! Bomba {room.teams[nxt]} ga o‘tdi!"
                else:
                    b["lives"][h] = max(0, b["lives"][h] - 1)
                    b["status"] = "boom"
                    b["last_msg"] = f"💥 Xato javob! {room.teams[h]} 1 ta jon yo‘qotdi!"

            elif act == "bomb_next" and room.bomb:
                b = room.bomb
                alive = [i for i, lv in enumerate(b["lives"]) if lv > 0]
                if len(alive) <= 1:
                    b["status"] = "gameover"
                    if alive:
                        room.scores[alive[0]] += 500
                        b["last_msg"] = f"🏆 G‘olib: {room.teams[alive[0]]}!"
                else:
                    nxt = alive[(alive.index(b["holder"]) + 1) % len(alive)] if b["holder"] in alive else alive[0]
                    b["holder"] = nxt
                    b["q_idx"] = (b["q_idx"] + 1) % len(b["pool"])
                    b["cur_q"] = b["pool"][b["q_idx"]]
                    b["deadline"] = time.time() + b["time_limit"]
                    b["time_left"] = b["time_limit"]
                    b["status"] = "playing"
                    b["last_choice"] = None
                    b["last_msg"] = f"💣 Navbat {room.teams[nxt]} da!"

            # Kahoot controls
            elif act == "kahoot_answer" and room.kahoot and room.kahoot["phase"] == "question":
                k = room.kahoot
                name = str(body.get("name") or "").strip()
                if name and name not in k["round_results"]:
                    team = max(0, min(3, int(body.get("team", room.players.get(name, 0)))))
                    rec = k["records"].setdefault(name, {"team": team, "pts": 0, "streak": 0, "correct": 0})
                    choice = max(0, min(3, int(body.get("choice", 0))))
                    ok = (choice == k["cur_q"]["c"])
                    rem = max(0, k["deadline"] - time.time())
                    gained = 0
                    if ok:
                        rec["streak"] += 1
                        rec["correct"] += 1
                        gained = 500 + int(500 * min(1.0, rem / 20.0)) + min(300, (rec["streak"] - 1) * 100)
                        rec["pts"] += gained
                        k["team_pts"][team] += gained
                    k["round_results"][name] = {"choice": choice, "ok": ok, "gained": gained}
                    if room.players and len(k["round_results"]) >= len(room.players):
                        room.kahoot_do_reveal()

            elif act == "kahoot_reveal" and room.kahoot:
                room.kahoot_do_reveal()

            elif act == "kahoot_next" and room.kahoot:
                k = room.kahoot
                if k["q_num"] < len(k["pool"]):
                    k["q_num"] += 1
                    k["cur_q"] = k["pool"][k["q_num"] - 1]
                    k["phase"] = "question"
                    k["deadline"] = time.time() + 20
                    k["time_left"] = 20
                    k["round_results"] = {}
                else:
                    k["phase"] = "podium"
                    for i in range(4):
                        room.scores[i] += k["team_pts"][i]

            room.touch()
            return self._send_json({"ok": True, **room.serialize(is_admin=is_adm)})


def main():
    if TELEGRAM_BOT_TOKEN:
        threading.Thread(target=telegram_bot_worker, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), QuizHandler)
    print(f"Jeo Quiz Pro server running on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
