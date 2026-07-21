from bus.event_bus import EventBus
from view.screen_manager import Screen, ScreenManager


class FakeScreen(Screen):
    def __init__(self, name):
        self.name = name
        self.rendered_on = []
        self.clicks = []
        self.double_clicks = []
        self.keys = []
        self.entered = 0
        self.exited = 0

    def on_enter(self):
        self.entered += 1

    def on_exit(self):
        self.exited += 1

    def render(self, canvas):
        self.rendered_on.append(canvas)

    def handle_click(self, x, y):
        self.clicks.append((x, y))

    def handle_double_click(self, x, y):
        self.double_clicks.append((x, y))

    def handle_key(self, key):
        self.keys.append(key)


def make_manager(initial="A"):
    events = EventBus()
    manager = ScreenManager(events, initial)
    a, b = FakeScreen("A"), FakeScreen("B")
    return manager, events, a, b


def test_starts_on_the_configured_initial_screen():
    manager, events, a, b = make_manager()
    manager.register("A", a)
    manager.register("B", b)

    assert manager.current_name == "A"
    assert manager.current is a


def test_go_to_switches_the_current_screen():
    manager, events, a, b = make_manager()
    manager.register("A", a)
    manager.register("B", b)

    manager.go_to("B")

    assert manager.current_name == "B"
    assert manager.current is b


def test_go_to_calls_exit_on_the_old_screen_and_enter_on_the_new_one():
    manager, events, a, b = make_manager()
    manager.register("A", a)
    manager.register("B", b)

    manager.go_to("B")

    assert a.exited == 1
    assert b.entered == 1
    assert a.entered == 0  # never re-entered
    assert b.exited == 0


def test_go_to_the_same_screen_is_a_no_op():
    manager, events, a, b = make_manager()
    manager.register("A", a)
    manager.register("B", b)

    manager.go_to("A")

    assert a.entered == 0
    assert a.exited == 0


def test_render_and_input_delegate_to_the_current_screen_only():
    manager, events, a, b = make_manager()
    manager.register("A", a)
    manager.register("B", b)

    manager.render("canvas-1")
    manager.handle_click(10, 20)
    manager.handle_double_click(30, 40)
    manager.handle_key(27)

    assert a.rendered_on == ["canvas-1"]
    assert a.clicks == [(10, 20)]
    assert a.double_clicks == [(30, 40)]
    assert a.keys == [27]
    assert b.rendered_on == []
    assert b.clicks == []


def test_transitions_are_wired_through_bus_events_not_hardcoded():
    # The whole point: publishing "login_success" moves the manager to HOME
    # without the render loop (or anything else) calling go_to() directly.
    manager, events, a, b = make_manager()
    manager.register("A", a, transitions={"login_success": "B"})
    manager.register("B", b)

    events.publish("login_success", {"user": "alice"})

    assert manager.current_name == "B"


def test_unrelated_events_do_not_trigger_a_transition():
    manager, events, a, b = make_manager()
    manager.register("A", a, transitions={"login_success": "B"})
    manager.register("B", b)

    events.publish("score_changed", {"color": "w", "score": 3})

    assert manager.current_name == "A"
