# סיכום שינויים - ממשק גרפי, אנימציות וכללי משחק (עם קוד)

> **איך לפתוח את הקובץ הזה בצורה נוחה:** ב-VS Code (שכבר פתוח אצלך על
> הפרויקט), לוחצים על הקובץ `CHANGES.he.md` בעץ הקבצים, ואז `Ctrl+Shift+V`
> (או הכפתור הקטן למעלה מימין "Open Preview") - זה יציג אותו מעוצב, עם
> הדגשת תחביר לקוד וכיוון RTL תקין לעברית.

## רקע

לפני העבודה הזו, ל-`kf-chess` היה רק רינדור טקסטואלי (`view/renderer.py`),
מופעל מסקריפט קבוע של פקודות (`main.py`). המטרה הייתה להוסיף ממשק גרפי
אמיתי עם אנימציות שעוקבות אחרי מהלכי המשחק בזמן אמת, תוך שימוש **רק**
בחומרים מהריפו שסופק (`KamaTechOrg/CTD26`) - בלי שום ספריית UI מעבר למה
שהריפו הזה עצמו משתמש בו (`opencv-python` דרך מחלקת `Img` הקטנה שלו).

---

## 1. ממשק גרפי + אנימציות

### `view/piece_assets.py` - מיפוי טוקן לתיקיית נכס

הלוח מייצג כלי כ-`"wP"` (צבע ואז סוג), אבל תיקיות הנכסים בריפו המקורי
בנויות הפוך - `"PW"` (סוג ואז צבע). זו הפונקציה שמגשרת בין השניים:

```python
def token_to_folder(token):
    """Board tokens are colour+kind (e.g. "wP"); asset folders are the
    opposite order, kind+colour (e.g. "PW")."""
    if len(token) != 2:
        raise InvalidTokenError(token)
    color, kind = token[0], token[1]
    return kind.upper() + color.upper()
```

לצד זה, `load_state_config` קוראת את ה-`config.json` של כל מצב (fps,
loop, המצב הבא) ו**סופרת בעצמה** כמה קובצי `.png` יש בתיקיית
`sprites/` - כך שמספר הפריימים לא מקודד בקוד, אלא נגזר מהדיסק:

```python
def load_state_config(folder, state, assets_root):
    state_dir = Path(assets_root) / folder / "states" / state
    with open(state_dir / "config.json", encoding="utf-8") as f:
        data = json.load(f)
    frame_count = len(list((state_dir / "sprites").glob("*.png")))
    return StateConfig(
        fps=data["graphics"]["frames_per_sec"],
        is_loop=data["graphics"]["is_loop"],
        next_state=data["physics"]["next_state_when_finished"],
        frame_count=frame_count,
    )
```

### `view/animation.py` - "המוח" של האנימציה

הפונקציה המרכזית `resolve_state_chain` מקבלת מצב התחלתי (למשל `"jump"`)
וכמה זמן עבר, והולכת לאורך שרשרת `next_state_when_finished` (jump ←
short_rest ← idle) עד שהיא מוצאת את המצב הנכון לרגע הזה:

```python
def resolve_state_chain(state_configs, start_state, elapsed_ms):
    state = start_state
    remaining = elapsed_ms
    visited = set()
    while True:
        cfg = state_configs[state]
        if cfg.next_state == state:      # idle מצביע על עצמו - זה הסוף
            return state, remaining

        duration_ms = state_duration_ms(cfg)   # frame_count/fps * 1000
        if remaining < duration_ms or state in visited:
            return state, remaining      # עדיין באמצע המצב הזה

        visited.add(state)
        remaining -= duration_ms
        state = cfg.next_state           # עוברים למצב הבא בשרשרת
```

**נקודה עדינה שגיליתי תוך כדי בדיקה:** ציפיתי ש-`is_loop=True` יסמן
"המצב הזה נשאר לתמיד", אבל בפועל גם `short_rest`/`long_rest` מסומנים
`is_loop=True` בנתונים בפועל (הספרייט שלהם חוזר על עצמו כל עוד הם
מוצגים) - ורק `idle` באמת "נשאר לתמיד" כי הוא היחיד שמצביע `next_state`
על עצמו. לכן הקוד בודק `next_state == state`, לא `is_loop`.

הפונקציה `compute_piece_views` היא זו שרצה על כל תא בלוח, בכל פריים,
ומחליטה מה להציג:

```python
if move is not None and move.piece == token:
    state = "move"
    x, y = interpolate_position(move.start, move.end, ...)
elif jump is not None and jump.piece == token:
    state, ms_into_state = resolve_state_chain(state_configs, "jump", ...)
elif arrival is not None and arrival.piece == token:
    start_state = "long_rest" if arrival.kind == "move" else "short_rest"
    state, ms_into_state = resolve_state_chain(state_configs, start_state, ...)
else:
    state = "idle"
```

כלומר: יש מהלך פעיל שמתחיל בתא הזה → מצב `move`. אין מהלך אבל יש קפיצה
פעילה → `jump` (עם שרשרת ה-rest). אין כלום פעיל אבל יש נחיתה אחרונה →
מתחילים משרשרת ה-rest המתאימה. אחרת → `idle`. הכל נגזר מהשוואת זמנים,
בלי לשמור "מצב נוכחי" בשום מקום.

### `view/graphics_renderer.py` - הציור בפועל

```python
def render(self, snapshot):
    canvas = self._board_canvas(snapshot.width, snapshot.height)
    if snapshot.selected is not None:
        self._draw_selection(canvas, snapshot.selected)
    for view in compute_piece_views(snapshot, self._piece_configs, self._config):
        sprite = self._sprite(view.folder, view.state, view.frame_index)
        sprite.draw_on(canvas, int(view.x), int(view.y))
    return canvas
```

כל קריאה ל-`render` בונה קנבס חדש מ-`board.png`, מציירת עליו את כל
הכלים במיקום ובפריים הנכונים (כולל אינטרפולציה חלקה בזמן תנועה), ומחזירה
תמונה מוכנה.

### `main_gui.py` - העכבר והלולאה

```python
def on_mouse(event, x, y, flags, userdata):
    if event == cv2.EVENT_LBUTTONDOWN:
        controller.click(x, y)
    elif event == cv2.EVENT_LBUTTONDBLCLK:
        controller.jump(x, y)
```

קליק בודד = הפעולה הרגילה (בחירה/הזזה), דאבל-קליק המובנה של `cv2` =
קפיצה. הלולאה הראשית מתקדמת לפי שעון אמיתי (`time.time()`), לא לפי
"תור":

```python
while True:
    now = time.time()
    dt_ms = int((now - last_time) * 1000)
    last_time = now
    engine.wait(dt_ms)
    snapshot = dataclasses.replace(engine.snapshot(), selected=controller.selected)
    canvas = renderer.render(snapshot)
    cv2.imshow(WINDOW_NAME, canvas.img)
```

---

## 2. חוק "מנוחה" אמיתי אחרי נחיתה

הבעיה: כלי שנחת יכול היה לפעול שוב מיד. נוספה `is_resting`, שמשתמשת
בחותמת הזמן של הנחיתה האחרונה (`_recent_arrivals`, שכבר הייתה שם בשביל
האנימציה) כדי לבדוק אם עדיין בתוך חלון הקירור:

```python
def is_resting(self, cell):
    arrival = self._recent_arrivals.get(cell)
    if arrival is None or self._board.get(*cell) != arrival.piece:
        return False
    duration = (
        self._config.SHORT_REST_DURATION if arrival.kind == "jump"
        else self._config.LONG_REST_DURATION
    )
    return self._clock < arrival.at + duration
```

ושורה אחת ב-`GameEngine` שמפעילה את זה בכל מקום שצריך (בחירה, מהלך,
קפיצה - כי כולם עוברים דרך `is_busy`):

```python
def is_busy(self, cell):
    return (
        self._arbiter.is_moving_from(cell)
        or self._arbiter.is_jumping_on(cell)
        or self._arbiter.is_resting(cell)      # <- השורה החדשה
    )
```

---

## 3. סנכרון זמן המנוחה לאנימציה בפועל

`state_duration_ms` מחשבת כמה זמן פריימי הספרייט אורכים בפועל:

```python
def state_duration_ms(cfg):
    return (cfg.frame_count / cfg.fps) * 1000 if cfg.fps else 0
```

ו-`main_gui.py` בונה, בהפעלה, עותק של הקונפיגורציה שבו זמני המנוחה
מוחלפים בערכים האמיתיים שנקראו מהקבצים (625 מ״ש אחרי קפיצה, 833 מ״ש
אחרי מהלך עם ערכת הדמויות הנוכחית):

```python
def with_synced_rest_durations(config):
    piece_configs = load_all_piece_configs(pieces_root)
    short = max(state_duration_ms(cfgs["short_rest"]) for cfgs in piece_configs.values())
    long_ = max(state_duration_ms(cfgs["long_rest"]) for cfgs in piece_configs.values())
    return types.SimpleNamespace(
        ...,
        SHORT_REST_DURATION=short,
        LONG_REST_DURATION=long_,
    )
```

`max()` על פני כל הכלים - ליתר ביטחון, למקרה שבעתיד יהיו לכלים שונים
אורכי אנימציה שונים (כרגע כולם זהים).

---

## 4. צביעת המשבצת בזמן המנוחה

גיליתי שאנימציית ה-rest כמעט זהה ל-idle ובקושי נראית. `rest_fraction`
מחושב לצד המצב עצמו - 1.0 מיד עם הנחיתה, יורד ל-0.0 בדיוק כשהקירור נגמר:

```python
def rest_fraction_remaining(elapsed_ms, rest_duration_ms):
    if not rest_duration_ms:
        return 0.0
    return max(0.0, min(1.0, 1.0 - elapsed_ms / rest_duration_ms))
```

והרנדרר מצייר מלבן כתום־שקוף בגובה יחסי, שנסוג *מלמעלה למטה* (כלומר
נשאר צבוע דווקא בתחתית המשבצת) ככל שהזמן עובר:

```python
def _draw_rest_overlay(self, canvas, cell, rest_fraction):
    height = int(round(rest_fraction * cell_size))
    top = row * cell_size + (cell_size - height)   # קצה עליון יורד בהדרגה
    bottom = row * cell_size + cell_size

    region = canvas.img[top:bottom, left:right, :3]
    blended = region.astype(np.float32) * (1 - REST_OVERLAY_MAX_ALPHA) + color * REST_OVERLAY_MAX_ALPHA
    region[:] = blended.astype(region.dtype)
```

---

## 5. שחזור תנועה מקבילה לשני הצבעים

מצאתי שההגדרה הקיימת חסמה כל מהלך שני בכל הלוח:

```python
# config/settings.py
ALLOW_CONCURRENT_MOVES = True   # היה False
```

```python
# game/engine.py, בתוך request_move
if not self._config.ALLOW_CONCURRENT_MOVES and self._arbiter.has_active_motion():
    return MoveResult(False, Reason.MOTION_IN_PROGRESS)
```

כשההגדרה `True` (ברירת המחדל עכשיו), התנאי הזה אף פעם לא מתקיים - אז
`request_move` ממשיך הלאה ומאשר את המהלך, לא משנה כמה מהלכים אחרים כבר
פעילים. ההגבלה היחידה שנשארת היא `is_busy(start)` - שבודקת רק את הכלי
הספציפי הזה, לא את הלוח כולו.

---

## 6. הודעת סיום משחק

`GameEngine` שומר עכשיו גם מי ניצח - מחשב את הצבע ההפוך מהכלי שנתפס:

```python
def _apply_events(self, events):
    for event in events:
        if self._win_condition.is_game_over(event.captured):
            self._game_over = True
            captured_color = event.captured[0]
            self._winner = next(c for c in self._config.COLORS if c != captured_color)
```

והרנדרר, כשה-snapshot מדווח `game_over=True`, מחשיך את כל הלוח וכותב
את ההודעה במרכז:

```python
def _draw_game_over_banner(self, canvas, snapshot):
    dim_region[:] = (dim_region.astype(np.float32) * (1 - GAME_OVER_DIM_ALPHA)).astype(dim_region.dtype)

    lines = ["GAME OVER"]
    if snapshot.winner is not None:
        name = COLOR_NAMES.get(snapshot.winner, snapshot.winner.upper())
        lines.append(f"{name} WINS")
    # ... ואז cv2.putText עבור כל שורה, ממורכז אופקית ואנכית
```

---

## מה עוד שווה לשפר

- **פער בין מצב טקסט לגרפי**: זמני המנוחה במצב טקסט (1000/3000 מ״ש)
  לא תואמים למה שרואים בפועל בממשק הגרפי (625/833 מ״ש) - לא מזיק כי
  אין ויזואל במצב טקסט בכלל.
- **אין הבדל צבע** בין ה-overlay של מנוחה אחרי קפיצה למנוחה אחרי מהלך.
- **אין עצירה מפורשת** של לולאת המשחק הגרפית כשהמשחק נגמר.
- **אין משוב על מהלך לא חוקי** - קליק על יעד לא חוקי מנקה בחירה בשקט.
- `build_game` ב-`main_gui.py` משכפל כ-15 שורות חיווט מ-`main.run`
  במקום לשתף קוד - החלטה מכוונת כדי לא לסכן את הנתיב הקיים והטסטים שלו.

## בדיקות

בכל שלב הרצתי את מלוא סוויטת הטסטים (138, כולל כל אלו שנוספו) וּוידאתי
שהיא עוברת. בנוסף בדקתי ידנית, כולל צילומי מסך: החלון נפתח, הלוח והכלים
מצוירים נכון, האנימציות רצות בזמן הנכון, ה-overlay מופיע ונעלם בדיוק
בזמן, והודעת הסיום מוצגת נכון עם שם המנצח.
