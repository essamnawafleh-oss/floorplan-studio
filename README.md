# Floor Plan Studio

مولّد مخططات منازل مبني على قواعد التصميم. بتعطيه أبعاد المبنى أو المساحات أو عدد السكان، وهو بيطلع مخطط كامل فيه جدران وأبواب وشبابيك وأبعاد. وبتقدر تصدّره **2D** (SVG) و**CAD** (DXF) و**3D** (GLB/OBJ).

A rule-based house floor plan generator. Give it dimensions, room areas or a household, get a complete plan with walls, doors, windows and dimensions, exported to 2D (SVG), CAD (DXF) and 3D (GLB/OBJ).

---

## الفكرة / How it works

1. **برنامج الفراغات:** من عدد السكان (أب وأم، أولاد، بنات، ضيوف) بيحسب البرنامج الغرف المطلوبة ومساحة كل وحدة حسب القواعد بملف `floorplan/rules/jordan.py`. مثلاً كل غرفة نوم فيها شخصين على الأكثر، والأولاد بغرف منفصلة عن البنات، ومساحة الصالون بتعتمد على عدد الضيوف. وإذا بدك، بتقدر تكتب الغرف ومساحاتها بنفسك.
2. **التوليد بالـ Seed:** الأبعاد الخارجية بتضل ثابتة، والـ Seed بيغيّر بس التوزيع. لكل Seed البرنامج بيجرب مئات الحلول، وبيختار الأفضل حسب القواعد:
   - المساحات
   - أقل عرض للغرفة
   - نسبة الطول للعرض
   - كل غرفة سكنية إلها شباك
   - كل غرفة إلها طريق من الباب الرئيسي
   - ما في غرفة الدخول إلها من غرفة نوم
   - المطبخ جنب السفرة، والصالون جنب المدخل
3. **الأبواب:** بتنبني كشجرة بتبدأ من الباب الرئيسي. لكل غرفة في قائمة "من وين بيندخل عليها"، والقائمة مرتبة حسب الأفضلية.
4. **التحذيرات:** كل مخالفة للقواعد بتطلع رسالة بالعربي والإنجليزي.

> ⚠️ أرقام القواعد ونظام الأبنية الموجودة بالبرنامج (الارتدادات ونسب البناء لسكن أ/ب/ج/د) **قيم تقريبية للبداية**. لازم تتأكد منها من النظام الساري قبل ما تعتمدها بأي مشروع. وكل قيمة فيها بتقدر تعدلها.

## التشغيل على ويندوز / Run on Windows (الأسهل)

1. نزّل وثبّت **Python** من https://www.python.org/downloads/. وقت التثبيت فعّل خيار **Add python.exe to PATH**.
2. نزّل المشروع من GitHub: كبسة **Code** الخضرا، بعدين **Download ZIP**، وفك الضغط.
3. كبسة دبل كليك على **`setup_windows.bat`**. هاي بتعملها مرة وحدة بس.
4. كبسة دبل كليك على **`run_windows.bat`**. بيطلع المخطط، وبيفتحلك مجلد `out`.
   - لتجرب مشروعك الخاص: انسخ ملف من مجلد `examples`، وعدّل الأرقام فيه بالمفكرة (Notepad)، بعدين **اسحبه وأفلته فوق** `run_windows.bat`.
   - ملفات `.svg` بتفتح بالمتصفح، و`.dxf` بالأوتوكاد، و`.glb` ببلندر أو 3D Viewer.

## التشغيل من سطر الأوامر / Command line

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 4 بدائل لنفس الأبعاد
.venv/bin/python -m floorplan examples/family.json --seeds 1 2 3 4 --out out

# الصيغ المتوفرة: svg dxf glb obj json
.venv/bin/python -m floorplan examples/fixed_rooms.json --seeds 7 --formats svg dxf obj
```

## ملف المشروع / Project file

```jsonc
{
  "project": "فيلا عائلة",
  "rules": "jordan",

  // اختار وحدة من هدول الثلاثة:
  "footprint": {"width": 18, "depth": 13},        // أبعاد ثابتة
  // "footprint": {"width": 14},                  // عرض ثابت والعمق بينحسب
  // "plot": {"width": 25, "depth": 32, "zoning": "amman_res_c"},  // قطعة أرض + تنظيم

  // الغرف إما من السكان...
  "household": {"parents": true, "sons": 2, "daughters": 1, "others": 0, "guests": 10,
                "office": false, "maid": false},
  // ...أو بتكتبها بنفسك (المساحة الثابتة بتتحافظ عليها):
  // "rooms": [{"type": "salon", "area": 22}, {"type": "bedroom", "occupants": 2}],

  "settings": {"exterior_wall": 0.30, "interior_wall": 0.15, "corridor": 1.20, "wall_height": 3.0},
  "lang": "both",     // لغة نصوص المخطط: ar | en | both
  "dxf_lang": "en"    // الإنجليزي أضمن بالأوتوكاد
}
```

أنواع الغرف المتوفرة: `entrance salon living dining kitchen guest_wc laundry storage maid master ensuite bedroom bathroom office`

## المخرجات / Outputs

| الملف | المحتوى |
|---|---|
| `.svg` | مخطط 2D ملوّن فيه أسماء الغرف ومساحاتها، والأبعاد، وفتحات الأبواب |
| `.dxf` | ملف CAD بطبقات: `A-WALL`, `A-WALL-HATCH`, `A-DOOR`, `A-GLAZ`, `A-AREA` (حدود الغرف لحساب المساحات), `A-ANNO-TEXT`, `A-ANNO-DIMS`. الوحدة متر |
| `.glb` / `.obj` | موديل 3D فيه الجدران، وفتحات الأبواب والشبابيك، والأعتاب، والزجاج، والأرضيات |
| `.json` | كل بيانات المخطط، لأي برنامج ثاني |

## هيكل الكود / Code layout

```
floorplan/
  rules/jordan.py   القواعد: أنواع الغرف، الحدود الدنيا، العلاقات، نظام الأبنية
  program.py        السكان أو الغرف -> برنامج الفراغات + حساب الأبعاد
  layout.py         المولّد والتقييم
  openings.py       الأبواب والشبابيك
  geometry.py       جيومتري الجدران (shapely)
  export/           svg / dxf / mesh3d
  cli.py            واجهة سطر الأوامر
tests/              اختبارات (pytest)
```

## خطة التطوير / Roadmap

- [x] **المرحلة 1:** المحرك، والقواعد الأردنية، والتوليد بالـ Seed، والتصدير SVG / DXF / GLB / OBJ
- [ ] **المرحلة 2:** برنامج سطح مكتب (PySide6) بالعربي والإنجليزي، فيه معاينة وتعديل يدوي للجدران والغرف
- [ ] **المرحلة 3:** معاينة 3D جوا البرنامج، ومواد، وأثاث أساسي، وتصدير PDF بلوحة عنوان ومقياس رسم
- [ ] **المرحلة 4:** أراضي غير منتظمة (من رفع مساحي أو DXF)، وأكثر من طابق مع درج، وتصدير IFC، وإضافة لبلندر
