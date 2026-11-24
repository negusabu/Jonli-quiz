import base64
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

PORT = int(os.environ.get("PORT", 8080))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
DEFAULT_ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234").strip()

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
                ("Blokcheyn texnologiyasi asosida yaratilgan birinchi kriptovalyuta?", ["Bitcoin", "Ethereum", "Solana", "Dogecoin"], 0, "Bitcoin 2009-yilda Satoshi Nakamoto taxallusi ostida ishga tushirilgan."),
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


def call_gemini(prompt_text, file_part=None):
    if not GEMINI_API_KEY:
        raise RuntimeError("Serverda GEMINI_API_KEY sozlanmagan.")
    parts = []
    if file_part:
        parts.append({"inline_data": {"mime_type": file_part["mime"], "data": file_part["b64"]}})
    parts.append({"text": prompt_text})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}"
    payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=70) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API xatosi ({e.code}): {err_body[:180]}")
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError("Gemini javob qaytarmadi.")
    out_parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in out_parts).strip()


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


def normalize_slide_item(raw_item, idx):
    layout = str(raw_item.get("layout") or ("cover" if idx == 0 else "bullets")).strip().lower()
    if layout not in ("cover", "bullets", "split", "stats", "quote", "summary"):
        layout = "bullets"
    bullets = [str(b).strip() for b in (raw_item.get("bullets") or []) if str(b).strip()][:6]
    stats_raw = raw_item.get("stats") or []
    stats = []
    for st in stats_raw[:4]:
        if isinstance(st, dict):
            lbl = str(st.get("label") or "").strip()
            val = str(st.get("value") or "").strip()
            if lbl or val:
                stats.append({"label": lbl, "value": val})
    return {
        "layout": layout,
        "badge": str(raw_item.get("badge") or f"{idx + 1:02d}-SLAYD").strip(),
        "title": str(raw_item.get("title") or f"Slayd #{idx + 1}").strip(),
        "subtitle": str(raw_item.get("subtitle") or "").strip(),
        "bullets": bullets,
        "highlight": str(raw_item.get("highlight") or "").strip(),
        "stats": stats,
        "notes": str(raw_item.get("notes") or "").strip(),
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
        items = [
            normalize_slide_item({
                "layout": "cover",
                "badge": "01 / TAQDIMOT",
                "title": self.topic_title or "Interaktiv Ma'ruza",
                "subtitle": f"{len(self.cats)} ta asosiy yo‘nalish • {len(self.questions)} ta tahliliy savol-javob",
                "bullets": self.cats,
                "highlight": "Jeo Quiz Pro Slayd Studio",
                "stats": [
                    {"label": "Bo‘limlar", "value": str(len(self.cats))},
                    {"label": "Savollar", "value": str(len(self.questions))},
                    {"label": "Format", "value": "Interaktiv"},
                ],
                "notes": "Kirish qismi: mavzuning umumiy tuzilishi va asosiy bo‘limlar bilan tanishtiring.",
            }, 0)
        ]
        for c_idx, cat in enumerate(self.cats):
            cat_qs = [q for q in self.questions if q["cat"] == cat][:5]
            bullets = []
            for q in cat_qs:
                ans_txt = q["opts"][q["c"]] if (q.get("opts") and q.get("c") is not None) else q.get("ans", "")
                bullets.append(f"{q['q']} → {ans_txt}")
            key_exp = cat_qs[0].get("exp", "") if cat_qs else ""
            items.append(
                normalize_slide_item({
                    "layout": "split" if c_idx % 2 == 0 else "bullets",
                    "badge": f"{c_idx + 2:02d} / BO‘LIM",
                    "title": cat,
                    "subtitle": f"{cat} yo‘nalishi bo‘yicha asosiy tushunchalar va qoidalar",
                    "bullets": bullets,
                    "highlight": key_exp or f"{cat} bo‘yicha muhim xulosalar",
                    "notes": f"{cat} bo‘limidagi asosiy faktlar va savol-javoblarni tushuntirib bering.",
                }, c_idx + 1)
            )
        items.append(
            normalize_slide_item({
                "layout": "summary",
                "badge": f"{len(items) + 1:02d} / XULOSA",
                "title": "Asosiy Xulosalar va Mustahkamlash",
                "subtitle": f"«{self.topic_title}» mavzusi yakuni",
                "bullets": [
                    "Barcha 5 ta asosiy yo‘nalish ko‘rib chiqildi",
                    "Bilimlarni tekshirish uchun Oddiy Test yoki Jonli O‘yin rejimiga o‘tish mumkin",
                    "Savol va takliflar uchun ochiq muhokama",
                ],
                "highlight": "E’tiboringiz uchun rahmat!",
                "notes": "Mavzuni yakunlang va talabalarni test yoki viktorinaga taklif qiling.",
            }, len(items))
        )
        self.slides = {
            "title": self.topic_title or "Pro Taqdimot",
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

        return {
            "room": self.code, "topic_title": self.topic_title, "presets": PRESETS_META,
            "ai_ready": bool(GEMINI_API_KEY), "ai_busy": self.ai_busy,
            "ai_status": self.ai_status, "ai_error": self.ai_error, "ai_note": self.ai_note,
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


def run_ai_board_worker(room, topic, level, file_part=None, extra_text=""):
    try:
        base_prompt = (
            f"O‘zbek tilida '{topic}' mavzusida ({level} uchun) Jeopardy va viktorina o‘yinlariga mos "
            f"5 ta bo‘lim va har bir bo‘limda 5 tadan — jami 25 ta test savol tuz.\n"
            f"Qat'iy JSON formatida javob ber:\n"
            f'{{"cats": ["Bo‘lim 1", "Bo‘lim 2", "Bo‘lim 3", "Bo‘lim 4", "Bo‘lim 5"], '
            f'"questions": [{{"cat": "Bo‘lim 1", "q": "Savol?", "opts": ["A", "B", "C", "D"], "c": 0, "exp": "Qisqa izoh"}} ...]}}\n'
            f"Talablar: 'questions' ro‘yxatida aynan 25 ta obyekt bo‘lsin (har bo‘limga 5 tadan, 100 dan 500 ballgacha qiyinlashib borsin), "
            f"'c' 0 dan 3 gacha to‘g‘ri variant indeksi bo‘lsin."
        )
        if extra_text:
            base_prompt += f"\n\nManba matni:\n{extra_text[:24000]}"

        raw = call_gemini(base_prompt, file_part=file_part)
        parsed = extract_json_block(raw)
        cats = parsed.get("cats") or []
        qs = parsed.get("questions") or []
        if len(cats) != 5 or len(qs) < 25:
            raise RuntimeError("AI 25 ta to‘liq savol qaytarmadi, qayta urinib ko‘ring.")

        formatted = []
        for idx in range(25):
            c_idx = idx // 5
            r_idx = idx % 5
            item = qs[idx]
            opts = [str(x) for x in (item.get("opts") or [])][:4]
            while len(opts) < 4:
                opts.append("Variant")
            c_val = int(item.get("c", 0))
            if c_val < 0 or c_val > 3:
                c_val = 0
            formatted.append({
                "cat": str(cats[c_idx]),
                "pts": (r_idx + 1) * 100,
                "q": str(item.get("q", "Savol")),
                "opts": opts,
                "c": c_val,
                "ans": opts[c_val],
                "exp": str(item.get("exp", "")),
            })

        with LOCK:
            room.cats = [str(x) for x in cats]
            room.questions = formatted
            room.topic_title = topic
            room.used = [False] * 25
            room.cur = None
            room.revealed = False
            room.answers = {}
            room.text_answers = {}
            room.ai_grades = {}
            room.ai_note = ""
            room.clear_subgames()
            room.ai_busy = False
            room.ai_error = ""
            room.ai_status = f"✔ «{topic}» bo‘yicha 25 ta savol tayyor!"
            room.touch()
    except Exception as e:
        with LOCK:
            room.ai_busy = False
            room.ai_error = str(e)
            room.ai_status = ""


def run_ai_slides_worker(room, topic, slide_count, style, theme, file_part=None, extra_text=""):
    try:
        prompt = (
            f"O‘zbek tilida '{topic}' mavzusida ({style} uslubida) aynan {slide_count} ta professional taqdimot slaydi yarat.\n"
            f"1-slayd albatta 'cover' (muqova), oxirgi slayd 'summary' (xulosa) bo‘lsin. Oraliq slaydlarda 'bullets', 'split', 'stats', 'quote' maketlarini navbatma-navbat ishlat.\n"
            f"Qat'iy JSON formatida javob ber:\n"
            f'{{"title": "Taqdimot sarlavhasi", "slides": ['
            f'{{"layout": "cover", "badge": "01 / KIRISH", "title": "Sarlavha", "subtitle": "Taglavha", '
            f'"bullets": ["Fikr 1", "Fikr 2", "Fikr 3"], "highlight": "Muhim xulosa yoki ta’rif", '
            f'"stats": [{{"label": "Ko‘rsatkich 1", "value": "85%"}}, {{"label": "Ko‘rsatkich 2", "value": "24/7"}}], '
            f'"notes": "Spiker uchun 2 jumlali nutq matni"}}'
            f"]}}\n"
            f"Talablar: Har bir slaydda 3-5 ta aniq, mazmunli va qisqa bullet punktlar bo‘lsin, matnlar ekranda chiroyli o‘qiladigan darajada lo‘nda yozilsin."
        )
        if extra_text:
            prompt += f"\n\nManba matni:\n{extra_text[:24000]}"

        raw = call_gemini(prompt, file_part=file_part)
        parsed = extract_json_block(raw)
        raw_slides = parsed.get("slides") or []
        if not raw_slides:
            raise RuntimeError("AI slaydlar ro‘yxatini qaytarmadi, qayta urinib ko‘ring.")

        items = [normalize_slide_item(it, i) for i, it in enumerate(raw_slides[:16])]
        deck_title = str(parsed.get("title") or topic).strip()

        with LOCK:
            room.slides = {
                "title": deck_title,
                "theme": theme,
                "cur_idx": 0,
                "items": items,
            }
            room.mode = "slides"
            room.ai_busy = False
            room.ai_error = ""
            room.ai_status = f"✔ «{deck_title}» bo‘yicha {len(items)} ta Pro slayd tayyor!"
            room.touch()
    except Exception as e:
        with LOCK:
            room.ai_busy = False
            room.ai_error = str(e)
            room.ai_status = ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filename):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        fpath = os.path.join(base_dir, filename)
        if not os.path.exists(fpath):
            self.send_json({"error": f"{filename} topilmadi"}, 404)
            return
        with open(fpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        ln = int(self.headers.get("Content-Length", 0))
        if ln <= 0:
            return {}
        return json.loads(self.rfile.read(ln).decode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self.send_file("index.html")
            return
        if path in ("/admin", "/admin.html"):
            self.send_file("admin.html")
            return

        if path == "/api/check_room":
            code = (qs.get("room") or [""])[0].strip()
            with LOCK:
                room = get_room(code)
                if not room:
                    self.send_json({"error": "Bunday xona topilmadi. Kodni tekshiring."}, 404)
                    return
                self.send_json({"ok": True, "room": room.code, "topic_title": room.topic_title})
            return

        if path == "/api/state":
            code = (qs.get("room") or ["0000"])[0]
            is_admin = (qs.get("admin") or ["0"])[0] == "1"
            pin = (qs.get("pin") or [""])[0]
            with LOCK:
                room = get_room(code)
                if not room:
                    self.send_json({"error": "Xona topilmadi"}, 404)
                    return
                if is_admin and pin != room.pin:
                    self.send_json({"error": "Noto‘g‘ri PIN kod"}, 403)
                    return
                self.send_json(room.serialize(is_admin=is_admin))
            return

        if path == "/api/questions":
            code = (qs.get("room") or ["0000"])[0]
            pin = (qs.get("pin") or [""])[0]
            with LOCK:
                room = get_room(code)
                if not room:
                    self.send_json({"error": "Xona topilmadi"}, 404)
                    return
                if pin != room.pin:
                    self.send_json({"error": "Noto‘g‘ri PIN kod"}, 403)
                    return
                self.send_json(room.questions)
            return

        self.send_json({"error": "Topilmadi"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            data = self.read_json()
        except Exception:
            self.send_json({"error": "Noto‘g‘ri JSON"}, 400)
            return

        if path == "/api/create_room":
            preset = str(data.get("preset") or "econ")
            teams = data.get("teams")
            with LOCK:
                cleanup_old_rooms()
                code = generate_room_code()
                pin = f"{random.randint(1000, 9999)}"
                room = Room(code, pin, preset_id=preset, teams=teams)
                ROOMS[code] = room
                st = room.serialize(is_admin=True)
            self.send_json({"ok": True, "room": code, "pin": pin, "state": st})
            return

        code = str(data.get("room") or "0000")

        if path == "/api/login":
            name = str(data.get("name") or "").strip()
            if not name:
                self.send_json({"error": "Ismingizni kiriting"}, 400)
                return
            tv = data.get("team")
            team = int(tv) if (tv is not None and tv != "" and 0 <= int(tv) < 4) else None
            with LOCK:
                room = get_room(code)
                if not room:
                    self.send_json({"error": "Xona topilmadi"}, 404)
                    return
                room.players[name] = team
                if room.kahoot and name not in room.kahoot["records"]:
                    room.kahoot["records"][name] = {"team": team, "pts": 0, "streak": 0, "correct": 0}
                room.touch()
            self.send_json({"ok": True})
            return

        if path == "/api/answer":
            team = data.get("team")
            with LOCK:
                room = get_room(code)
                if not room or team is None or not (0 <= int(team) < 4):
                    self.send_json({"error": "Jamoa tanlanmagan"}, 400)
                    return
                t = int(team)
                if "choice" in data and data["choice"] is not None:
                    room.answers[t] = int(data["choice"])
                if "text" in data and data["text"] is not None:
                    room.text_answers[t] = str(data["text"]).strip()
                room.touch()
            self.send_json({"ok": True})
            return

        if path == "/api/classic_test_submit":
            name = str(data.get("name") or "").strip()
            tv = data.get("team")
            team = int(tv) if (tv is not None and tv != "" and 0 <= int(tv) < 4) else None
            answers = data.get("answers") or []
            dur_sec = max(1, int(data.get("duration_sec") or 0))
            with LOCK:
                room = get_room(code)
                if not room or not room.classic_test:
                    self.send_json({"error": "Oddiy test faol emas"}, 400)
                    return
                ct = room.classic_test
                if not ct["active"]:
                    self.send_json({"error": "Test yakunlangan, javob qabul qilinmaydi"}, 400)
                    return
                if not name:
                    self.send_json({"error": "Ismingizni kiriting"}, 400)
                    return

                pool = ct["pool"]
                correct_cnt = 0
                total_score = 0
                review = []
                for idx, q in enumerate(pool):
                    uch = answers[idx] if idx < len(answers) and answers[idx] is not None else -1
                    uch = int(uch)
                    is_ok = (uch == q["c"])
                    if is_ok:
                        correct_cnt += 1
                        total_score += int(q.get("pts") or 100)
                    review.append({
                        "idx": idx,
                        "cat": q["cat"],
                        "q": q["q"],
                        "opts": list(q["opts"]),
                        "user_choice": uch,
                        "correct_choice": q["c"],
                        "is_correct": is_ok,
                        "exp": q.get("exp", "") if ct["show_explanations"] else "",
                    })

                total_q = max(1, len(pool))
                pct = int(round(correct_cnt * 100 / total_q))
                prev = ct["submissions"].get(name)
                sub_obj = {
                    "name": name,
                    "team": team,
                    "correct": correct_cnt,
                    "total": len(pool),
                    "percent": pct,
                    "score": total_score,
                    "duration_sec": dur_sec,
                    "submitted_at": time.time(),
                    "review": review,
                }
                ct["submissions"][name] = sub_obj
                if not prev and team is not None and 0 <= team < 4:
                    ct["team_pts"][team] += total_score
                room.touch()
            self.send_json({"ok": True, "result": sub_obj})
            return

        if path == "/api/kahoot_play":
            name = str(data.get("name") or "").strip()
            tv = data.get("team")
            team = int(tv) if (tv is not None and tv != "" and 0 <= int(tv) < 4) else None
            choice = int(data.get("choice", -1))
            with LOCK:
                room = get_room(code)
                if not room or not room.kahoot:
                    self.send_json({"error": "Jonli TEST o‘yini faol emas"}, 400)
                    return
                room.tick_timers()
                k = room.kahoot
                if k["phase"] != "question":
                    self.send_json({"error": "Savol vaqti tugagan"}, 400)
                    return
                if not name:
                    self.send_json({"error": "Ism kiritilmagan"}, 400)
                    return
                if name in k["round_results"]:
                    self.send_json({"ok": True})
                    return
                if name not in k["records"]:
                    k["records"][name] = {"team": team, "pts": 0, "streak": 0, "correct": 0}
                rec = k["records"][name]
                if team is not None:
                    rec["team"] = team
                q = k["cur_q"]
                is_ok = (choice == q["c"])
                gained = 0
                if is_ok:
                    dur = max(1, k["duration"])
                    rem = max(0.0, k["deadline"] - time.time())
                    speed_pts = int(round(500 + 500 * (rem / dur)))
                    rec["streak"] += 1
                    rec["correct"] += 1
                    streak_bonus = min(500, (rec["streak"] - 1) * 100)
                    gained = speed_pts + streak_bonus
                    rec["pts"] += gained
                    if rec["team"] is not None and 0 <= rec["team"] < 4:
                        k["team_pts"][rec["team"]] += gained
                else:
                    rec["streak"] = 0
                k["round_results"][name] = {"choice": choice, "ok": is_ok, "gained": gained}
                total_known = max(len(room.players), len(k["records"]))
                if total_known > 0 and len(k["round_results"]) >= total_known:
                    room.kahoot_do_reveal()
                room.touch()
            self.send_json({"ok": True})
            return

        if path == "/api/mil_play":
            action = data.get("action")
            with LOCK:
                room = get_room(code)
                if not room or not room.mil:
                    self.send_json({"error": "Millioner o‘yini faol emas"}, 400)
                    return
                m = room.mil
                mq = m["pool"][m["step"]]
                if action == "select" and m["active"] and not m["revealed"]:
                    m["selected"] = int(data.get("choice"))
                elif action == "5050" and m["active"] and not m["revealed"] and m["lifelines"]["fifty"]:
                    wrong = [i for i in range(4) if i != mq["c"]]
                    m["hidden_opts"] = random.sample(wrong, 2)
                    m["lifelines"]["fifty"] = False
                elif action == "audience" and m["active"] and not m["revealed"] and m["lifelines"]["audience"]:
                    m["audience_open"] = True
                    m["lifelines"]["audience"] = False
                elif action == "ai" and m["active"] and not m["revealed"] and m["lifelines"]["ai"]:
                    m["lifelines"]["ai"] = False
                    if GEMINI_API_KEY:
                        try:
                            m["ai_hint"] = call_gemini(
                                f"«Kim millioner bo‘lishni xohlaydi?» o‘yinida yordam ber. Savol: {mq['q']}. "
                                f"Variantlar: A){mq['opts'][0]}, B){mq['opts'][1]}, C){mq['opts'][2]}, D){mq['opts'][3]}. "
                                f"2 jumlada qisqa maslahat ber."
                            )
                        except Exception:
                            m["ai_hint"] = f"Eng ishonchli javob: {['A','B','C','D'][mq['c']]} varianti."
                    else:
                        m["ai_hint"] = f"Eng to‘g‘ri yo‘nalish: {['A','B','C','D'][mq['c']]} varianti."
                elif action == "reveal" and m["active"] and not m["revealed"] and m["selected"] is not None:
                    m["revealed"] = True
                    m["audience_open"] = False
                    if m["selected"] == mq["c"]:
                        m["won"] = MIL_PRIZES[m["step"]]
                        if m["step"] >= len(MIL_PRIZES) - 1:
                            m["active"] = False
                            m["status"] = "won"
                    else:
                        safe_won = 0
                        for s_idx in MIL_SAFES:
                            if m["step"] > s_idx:
                                safe_won = MIL_PRIZES[s_idx]
                        m["won"] = safe_won
                        m["active"] = False
                        m["status"] = "lost"
                elif action == "next" and m["active"] and m["revealed"] and m["status"] == "playing":
                    m["step"] += 1
                    m["revealed"] = False
                    m["selected"] = None
                    m["hidden_opts"] = []
                    m["audience_open"] = False
                    m["votes"] = {}
                    m["ai_hint"] = ""
                elif action == "walk" and m["active"] and m["won"] > 0:
                    m["active"] = False
                    m["status"] = "walked"
                room.touch()
            self.send_json({"ok": True})
            return

        if path == "/api/mil_vote":
            voter = str(data.get("voter") or "mehmon")
            choice = int(data.get("choice", 0))
            with LOCK:
                room = get_room(code)
                if room and room.mil and room.mil["audience_open"]:
                    room.mil["votes"][voter] = choice
                    room.touch()
            self.send_json({"ok": True})
            return

        if path == "/api/auc_play":
            action = data.get("action")
            team = int(data.get("team", -1))
            with LOCK:
                room = get_room(code)
                if not room or not room.auc or not (0 <= team < 4):
                    self.send_json({"error": "Auksion faol emas"}, 400)
                    return
                a = room.auc
                if action == "bet" and a["phase"] == "betting":
                    amt = max(10, min(a["bank"][team], int(data.get("amount", 50))))
                    a["bets"][str(team)] = amt
                elif action == "answer" and a["phase"] == "question":
                    a["answers"][str(team)] = int(data.get("choice", 0))
                room.touch()
            self.send_json({"ok": True})
            return

        if path == "/api/bomb_play":
            team = int(data.get("team", -1))
            choice = int(data.get("choice", -1))
            with LOCK:
                room = get_room(code)
                if not room or not room.bomb:
                    self.send_json({"error": "Bomba o‘yini faol emas"}, 400)
                    return
                room.tick_timers()
                b = room.bomb
                if b["status"] != "playing" or team != b["holder"]:
                    self.send_json({"ok": True})
                    return
                b["last_choice"] = choice
                if choice == b["cur_q"]["c"]:
                    alive = [i for i in range(4) if b["lives"][i] > 0]
                    nxt = (team + 1) % 4
                    for _ in range(4):
                        if b["lives"][nxt] > 0:
                            break
                        nxt = (nxt + 1) % 4
                    b["holder"] = nxt
                    b["pool_idx"] = (b["pool_idx"] + 1) % len(b["pool"])
                    b["cur_q"] = b["pool"][b["pool_idx"]]
                    b["deadline"] = time.time() + b["sec"]
                    b["time_left"] = b["sec"]
                    b["last_choice"] = None
                    if len(alive) <= 1:
                        b["status"] = "win"
                        b["last_msg"] = f"👑 G‘OLIB: {room.teams[alive[0]]}!"
                    else:
                        b["last_msg"] = f"✅ {room.teams[team]} to‘g‘ri topdi! Bomba {room.teams[nxt]} ga o‘tdi!"
                else:
                    b["lives"][team] = max(0, b["lives"][team] - 1)
                    b["status"] = "boom"
                    b["last_msg"] = f"💥 XATO! Bomba {room.teams[team]} qo‘lida portladi (−1 jon)!"
                room.touch()
            self.send_json({"ok": True})
            return

        if path == "/api/admin":
            pin = str(data.get("pin") or "")
            action = str(data.get("action") or "")
            with LOCK:
                room = get_room(code)
                if not room:
                    self.send_json({"error": "Xona topilmadi"}, 404)
                    return
                if pin != room.pin:
                    self.send_json({"error": "Noto‘g‘ri PIN kod"}, 403)
                    return

                if action == "load_preset":
                    room.load_preset(str(data.get("preset") or "econ"))

                elif action == "set_mode":
                    mode = str(data.get("mode") or "jeopardy")
                    if mode in ("jeopardy", "millionaire", "auction", "bomb", "kahoot", "slides", "classic_test"):
                        room.mode = mode
                        if mode == "slides" and not room.slides:
                            room.build_slides_from_current_questions()
                        elif mode == "classic_test" and not room.classic_test:
                            pool = room.get_mc_pool()
                            room.classic_test = {
                                "active": True,
                                "title": room.topic_title or "Oddiy Test",
                                "time_limit": 0,
                                "show_explanations": True,
                                "pool": pool,
                                "submissions": {},
                                "team_pts": [0, 0, 0, 0],
                            }

                elif action == "open":
                    idx = int(data.get("idx", 0))
                    room.cur = idx
                    room.revealed = False
                    room.answers = {}
                    room.text_answers = {}
                    room.ai_grades = {}
                    room.ai_note = ""

                elif action == "reveal":
                    room.revealed = True
                    if room.cur is not None:
                        room.used[room.cur] = True

                elif action == "close":
                    if room.cur is not None:
                        room.used[room.cur] = True
                    room.cur = None
                    room.revealed = False
                    room.ai_note = ""

                elif action == "award":
                    t = int(data.get("team", 0))
                    sign = int(data.get("sign", 1))
                    if room.cur is not None and 0 <= t < 4:
                        room.scores[t] += sign * room.questions[room.cur]["pts"]

                elif action == "score":
                    t = int(data.get("team", 0))
                    delta = int(data.get("delta", 0))
                    if 0 <= t < 4:
                        room.scores[t] += delta

                elif action == "rename":
                    tms = data.get("teams") or []
                    for i in range(min(4, len(tms))):
                        if str(tms[i]).strip():
                            room.teams[i] = str(tms[i]).strip()

                elif action == "reset":
                    room.scores = [0, 0, 0, 0]
                    room.used = [False] * 25
                    room.cur = None
                    room.revealed = False
                    room.answers = {}
                    room.text_answers = {}
                    room.ai_grades = {}
                    room.ai_note = ""
                    room.clear_subgames()

                elif action == "save":
                    idx = int(data.get("idx", 0))
                    q_in = data.get("q") or {}
                    if 0 <= idx < 25:
                        old = room.questions[idx]
                        short = bool(q_in.get("short"))
                        opts = [] if short else [str(x) for x in (q_in.get("opts") or ["", "", "", ""])][:4]
                        c_val = None if short else (int(q_in["c"]) if q_in.get("c") is not None else 0)
                        room.questions[idx] = {
                            "cat": old["cat"], "pts": old["pts"], "q": str(q_in.get("q") or ""),
                            "opts": opts, "c": c_val,
                            "ans": str(q_in.get("ans") or "") if short else (opts[c_val] if opts else ""),
                            "exp": str(q_in.get("exp") or ""),
                        }

                elif action == "ai_generate_board":
                    if room.ai_busy:
                        self.send_json({"error": "AI hozir band, biroz kuting"}, 400)
                        return
                    topic = str(data.get("topic") or "").strip()
                    level = str(data.get("level") or "universitet talabalari")
                    room.ai_busy = True
                    room.ai_error = ""
                    room.ai_status = f"«{topic}» mavzusida 25 ta savol tuzilmoqda..."
                    threading.Thread(target=run_ai_board_worker, args=(room, topic, level), daemon=True).start()

                elif action == "ai_generate_from_file":
                    if room.ai_busy:
                        self.send_json({"error": "AI hozir band"}, 400)
                        return
                    fname = str(data.get("filename") or "fayl")
                    mime = str(data.get("mime") or "")
                    b64 = str(data.get("data_b64") or "")
                    hint = str(data.get("hint") or "").strip()
                    level = str(data.get("level") or "universitet talabalari")
                    topic_lbl = hint if hint else fname
                    room.ai_busy = True
                    room.ai_error = ""
                    room.ai_status = f"«{fname}» fayli tahlil qilinmoqda..."
                    file_part = None
                    extra_txt = ""
                    if fname.lower().endswith(".docx"):
                        extra_txt = extract_docx_text(b64)
                    elif fname.lower().endswith((".txt", ".md", ".csv")):
                        extra_txt = base64.b64decode(b64).decode("utf-8", errors="ignore")[:28000]
                    else:
                        if not mime:
                            mime = "application/pdf" if fname.lower().endswith(".pdf") else "image/jpeg"
                        file_part = {"mime": mime, "b64": b64}
                    threading.Thread(target=run_ai_board_worker, args=(room, topic_lbl, level, file_part, extra_txt), daemon=True).start()

                elif action == "ai_generate_slot":
                    idx = int(data.get("idx", 0))
                    hint = str(data.get("hint") or "").strip()
                    old = room.questions[idx]
                    raw = call_gemini(
                        f"O‘zbek tilida '{old['cat']}' bo‘limi uchun {old['pts']} ballik 1 ta test savol tuz. "
                        f"Qo‘shimcha ko‘rsatma: {hint}. JSON qaytar: "
                        f'{{"q": "...", "opts": ["A", "B", "C", "D"], "c": 0, "exp": "..."}}'
                    )
                    parsed = extract_json_block(raw)
                    room.touch()
                    self.send_json({"ok": True, "question": parsed})
                    return

                elif action == "ai_explain":
                    if room.cur is not None:
                        q = room.questions[room.cur]
                        ans_s = q["opts"][q["c"]] if q["opts"] else q["ans"]
                        room.ai_note = call_gemini(
                            f"Ushbu savol va to‘g‘ri javobga talabalar uchun 3 jumlada amaliy misol va tushuntirish ber (o‘zbek tilida):\n"
                            f"Savol: {q['q']}\nJavob: {ans_s}"
                        )

                elif action == "ai_grade":
                    if room.cur is not None:
                        q = room.questions[room.cur]
                        lines = [f"{i}: {room.text_answers.get(i, '')}" for i in range(4) if room.text_answers.get(i)]
                        if lines:
                            raw = call_gemini(
                                f"Savol: {q['q']}\nEtalon javob: {q['ans']}\nJamoalar javobi:\n" + "\n".join(lines) +
                                '\nHar bir jamoa uchun JSON qaytar: {"0": {"percent": 85, "verdict": "To‘g‘ri", "comment": "Qisqa izoh"}}'
                            )
                            room.ai_grades = extract_json_block(raw)

                # --- PRO SLAYD STUDIO ---
                elif action == "ai_generate_slides":
                    if room.ai_busy:
                        self.send_json({"error": "AI hozir band, biroz kuting"}, 400)
                        return
                    topic = str(data.get("topic") or room.topic_title or "Taqdimot").strip()
                    slide_count = max(4, min(16, int(data.get("slide_count") or 8)))
                    style = str(data.get("style") or "Akademik ma’ruza").strip()
                    theme = str(data.get("theme") or "royal").strip()
                    fname = str(data.get("filename") or "").strip()
                    mime = str(data.get("mime") or "").strip()
                    b64 = str(data.get("data_b64") or "").strip()

                    file_part = None
                    extra_txt = ""
                    if b64 and fname:
                        if fname.lower().endswith(".docx"):
                            extra_txt = extract_docx_text(b64)
                        elif fname.lower().endswith((".txt", ".md", ".csv")):
                            extra_txt = base64.b64decode(b64).decode("utf-8", errors="ignore")[:28000]
                        else:
                            if not mime:
                                mime = "application/pdf" if fname.lower().endswith(".pdf") else "image/jpeg"
                            file_part = {"mime": mime, "b64": b64}

                    room.ai_busy = True
                    room.ai_error = ""
                    room.ai_status = f"«{topic}» bo‘yicha {slide_count} ta Pro slayd tayyorlanmoqda..."
                    threading.Thread(
                        target=run_ai_slides_worker,
                        args=(room, topic, slide_count, style, theme, file_part, extra_txt),
                        daemon=True,
                    ).start()

                elif action == "slides_from_questions":
                    theme = str(data.get("theme") or (room.slides["theme"] if room.slides else "royal"))
                    room.build_slides_from_current_questions(theme=theme)
                    room.mode = "slides"

                elif action == "slides_nav" and room.slides:
                    idx = int(data.get("idx", 0))
                    total = len(room.slides["items"])
                    if total > 0:
                        room.slides["cur_idx"] = max(0, min(total - 1, idx))

                elif action == "slides_theme" and room.slides:
                    theme = str(data.get("theme") or "royal")
                    room.slides["theme"] = theme

                elif action == "slides_save_item" and room.slides:
                    idx = int(data.get("idx", 0))
                    s_in = data.get("slide") or {}
                    if 0 <= idx < len(room.slides["items"]):
                        room.slides["items"][idx] = normalize_slide_item(s_in, idx)

                elif action == "slides_add_item" and room.slides:
                    new_idx = len(room.slides["items"])
                    room.slides["items"].append(
                        normalize_slide_item({
                            "layout": "bullets",
                            "badge": f"{new_idx + 1:02d} / YANGI",
                            "title": "Yangi slayd sarlavhasi",
                            "subtitle": "Qo‘shimcha ma’lumot",
                            "bullets": ["Birinchi muhim fikr", "Ikkinchi muhim fikr"],
                            "highlight": "Asosiy xulosa",
                            "notes": "",
                        }, new_idx)
                    )
                    room.slides["cur_idx"] = new_idx

                elif action == "slides_delete_item" and room.slides:
                    idx = int(data.get("idx", 0))
                    if len(room.slides["items"]) > 1 and 0 <= idx < len(room.slides["items"]):
                        room.slides["items"].pop(idx)
                        room.slides["cur_idx"] = min(room.slides["cur_idx"], len(room.slides["items"]) - 1)

                # --- ODDIY TEST (CLASSIC SELF-PACED TEST) ---
                elif action == "ctest_start":
                    q_count = max(1, min(25, int(data.get("q_count") or 25)))
                    time_limit = max(0, min(180, int(data.get("time_limit") or 0)))
                    shuffle_q = bool(data.get("shuffle", False))
                    show_exp = bool(data.get("show_explanations", True))
                    title = str(data.get("title") or room.topic_title or "Oddiy Test").strip()

                    pool = [copy.deepcopy(q) for q in room.questions if len(q.get("opts") or []) == 4 and q.get("c") is not None]
                    if not pool:
                        pool = copy.deepcopy(PRESET_DATA["econ"]["questions"])
                    if shuffle_q:
                        random.shuffle(pool)
                    pool = pool[:q_count]

                    room.classic_test = {
                        "active": True,
                        "title": title,
                        "time_limit": time_limit,
                        "show_explanations": show_exp,
                        "pool": pool,
                        "submissions": {},
                        "team_pts": [0, 0, 0, 0],
                    }
                    room.mode = "classic_test"

                elif action == "ctest_toggle" and room.classic_test:
                    room.classic_test["active"] = not room.classic_test["active"]

                elif action == "ctest_sync_scores" and room.classic_test:
                    for i in range(4):
                        room.scores[i] += room.classic_test["team_pts"][i]
                    room.classic_test["team_pts"] = [0, 0, 0, 0]

                # --- MILLIONAIRE ---
                elif action == "mil_start":
                    pname = str(data.get("player") or "").strip() or "Ishtirokchi"
                    tv = data.get("team")
                    t_idx = int(tv) if (tv is not None and tv != "") else None
                    pool = room.get_mc_pool()
                    while len(pool) < len(MIL_PRIZES):
                        pool.extend(room.get_mc_pool())
                    room.mil = {
                        "active": True, "player": pname, "team": t_idx,
                        "pool": pool[:len(MIL_PRIZES)], "step": 0, "won": 0,
                        "status": "playing", "revealed": False, "selected": None,
                        "hidden_opts": [], "lifelines": {"fifty": True, "audience": True, "ai": True},
                        "audience_open": False, "votes": {}, "ai_hint": "", "credited": False,
                    }

                elif action == "mil_select" and room.mil:
                    room.mil["selected"] = int(data.get("choice"))

                elif action == "mil_5050" and room.mil and room.mil["lifelines"]["fifty"]:
                    mq = room.mil["pool"][room.mil["step"]]
                    wrong = [i for i in range(4) if i != mq["c"]]
                    room.mil["hidden_opts"] = random.sample(wrong, 2)
                    room.mil["lifelines"]["fifty"] = False

                elif action == "mil_audience" and room.mil and room.mil["lifelines"]["audience"]:
                    room.mil["audience_open"] = True
                    room.mil["lifelines"]["audience"] = False

                elif action == "mil_ai" and room.mil and room.mil["lifelines"]["ai"]:
                    mq = room.mil["pool"][room.mil["step"]]
                    room.mil["lifelines"]["ai"] = False
                    if GEMINI_API_KEY:
                        room.mil["ai_hint"] = call_gemini(
                            f"Savol: {mq['q']}. Variantlar: {mq['opts']}. 2 jumlada qisqa maslahat ber (o‘zbek tilida)."
                        )
                    else:
                        room.mil["ai_hint"] = f"Eng mantiqiy variant: {['A','B','C','D'][mq['c']]}."

                elif action == "mil_reveal" and room.mil and room.mil["selected"] is not None:
                    m = room.mil
                    mq = m["pool"][m["step"]]
                    m["revealed"] = True
                    m["audience_open"] = False
                    if m["selected"] == mq["c"]:
                        m["won"] = MIL_PRIZES[m["step"]]
                        if m["step"] >= len(MIL_PRIZES) - 1:
                            m["active"] = False
                            m["status"] = "won"
                    else:
                        safe_won = 0
                        for s_idx in MIL_SAFES:
                            if m["step"] > s_idx:
                                safe_won = MIL_PRIZES[s_idx]
                        m["won"] = safe_won
                        m["active"] = False
                        m["status"] = "lost"

                elif action == "mil_next" and room.mil:
                    m = room.mil
                    m["step"] += 1
                    m["revealed"] = False
                    m["selected"] = None
                    m["hidden_opts"] = []
                    m["audience_open"] = False
                    m["votes"] = {}
                    m["ai_hint"] = ""

                elif action == "mil_walk" and room.mil:
                    room.mil["active"] = False
                    room.mil["status"] = "walked"

                elif action == "mil_credit" and room.mil and not room.mil["credited"]:
                    t_idx = room.mil["team"]
                    if t_idx is not None and 0 <= t_idx < 4:
                        room.scores[t_idx] += room.mil["won"]
                        room.mil["credited"] = True

                # --- AUCTION ---
                elif action == "auc_start":
                    pool = room.get_mc_pool()[:8]
                    room.auc = {
                        "round": 1, "total_rounds": len(pool), "pool": pool,
                        "phase": "betting", "bank": [1000, 1000, 1000, 1000],
                        "bets": {}, "answers": {}, "deltas": [0, 0, 0, 0],
                    }

                elif action == "auc_open_q" and room.auc:
                    a = room.auc
                    for i in range(4):
                        if str(i) not in a["bets"]:
                            a["bets"][str(i)] = min(100, a["bank"][i])
                    a["phase"] = "question"

                elif action == "auc_reveal" and room.auc:
                    a = room.auc
                    aq = a["pool"][a["round"] - 1]
                    deltas = [0, 0, 0, 0]
                    for i in range(4):
                        bet = int(a["bets"].get(str(i), 0))
                        ans = a["answers"].get(str(i))
                        if ans is not None and int(ans) == aq["c"]:
                            a["bank"][i] += bet
                            deltas[i] = bet
                        else:
                            a["bank"][i] = max(100, a["bank"][i] - bet)
                            deltas[i] = -bet
                    a["deltas"] = deltas
                    a["phase"] = "revealed"

                elif action == "auc_next" and room.auc:
                    a = room.auc
                    if a["round"] < a["total_rounds"]:
                        a["round"] += 1
                        a["phase"] = "betting"
                        a["bets"] = {}
                        a["answers"] = {}
                        a["deltas"] = [0, 0, 0, 0]

                elif action == "auc_sync_scores" and room.auc:
                    for i in range(4):
                        room.scores[i] += room.auc["bank"][i]

                # --- BOMB ---
                elif action == "bomb_start":
                    sec = int(data.get("sec", 20))
                    pool = room.get_mc_pool()
                    room.bomb = {
                        "holder": 0, "lives": [3, 3, 3, 3], "sec": sec,
                        "deadline": time.time() + sec, "time_left": sec,
                        "status": "playing", "last_choice": None,
                        "last_msg": f"💣 Bomba {room.teams[0]} qo‘lida! Tez javob bering!",
                        "pool": pool, "pool_idx": 0, "cur_q": pool[0],
                    }

                elif action == "bomb_resume" and room.bomb:
                    b = room.bomb
                    alive = [i for i in range(4) if b["lives"][i] > 0]
                    if len(alive) <= 1:
                        b["status"] = "win"
                        winner = room.teams[alive[0]] if alive else "Hech kim"
                        b["last_msg"] = f"👑 G‘OLIB: {winner}!"
                    else:
                        nxt = (b["holder"] + 1) % 4
                        for _ in range(4):
                            if b["lives"][nxt] > 0:
                                break
                            nxt = (nxt + 1) % 4
                        b["holder"] = nxt
                        b["pool_idx"] = (b["pool_idx"] + 1) % len(b["pool"])
                        b["cur_q"] = b["pool"][b["pool_idx"]]
                        b["deadline"] = time.time() + b["sec"]
                        b["time_left"] = b["sec"]
                        b["last_choice"] = None
                        b["status"] = "playing"
                        b["last_msg"] = f"💣 Bomba {room.teams[nxt]} ga uzatildi!"

                # --- JONLI TEST (KAHOOT) ---
                elif action == "kahoot_start":
                    dur = int(data.get("duration", 20))
                    pool = room.get_mc_pool()[:15]
                    recs = {nm: {"team": tm, "pts": 0, "streak": 0, "correct": 0} for nm, tm in room.players.items()}
                    room.kahoot = {
                        "phase": "lobby", "duration": dur, "pool": pool,
                        "q_num": -1, "cur_q": None, "deadline": 0,
                        "time_left": dur, "round_results": {}, "records": recs,
                        "team_pts": [0, 0, 0, 0],
                    }

                elif action == "kahoot_next" and room.kahoot:
                    k = room.kahoot
                    if k["q_num"] + 1 < len(k["pool"]):
                        k["q_num"] += 1
                        k["cur_q"] = k["pool"][k["q_num"]]
                        k["phase"] = "question"
                        k["deadline"] = time.time() + k["duration"]
                        k["time_left"] = k["duration"]
                        k["round_results"] = {}

                elif action == "kahoot_reveal" and room.kahoot:
                    room.kahoot_do_reveal()

                elif action == "kahoot_podium" and room.kahoot:
                    room.kahoot["phase"] = "podium"

                elif action == "kahoot_sync_scores" and room.kahoot:
                    for i in range(4):
                        room.scores[i] += room.kahoot["team_pts"][i]
                    room.kahoot["team_pts"] = [0, 0, 0, 0]

                room.touch()
                st = room.serialize(is_admin=True)
            self.send_json(st)
            return

        self.send_json({"error": "Noma’lum so‘rov"}, 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"JEO QUIZ universal server ishga tushdi: port {PORT}", flush=True)
    server.serve_forever()
