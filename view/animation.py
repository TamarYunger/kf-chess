from dataclasses import dataclass

from view.piece_assets import token_to_folder


def resolve_state_chain(state_configs, start_state, elapsed_ms):
    """Walks the next_state_when_finished chain starting at `start_state`,
    consuming `elapsed_ms` as it goes, until it either reaches a terminal
    state or elapsed_ms runs out mid-state. Returns
    (state_name, ms_into_that_state).

    A state is terminal when its own next_state_when_finished points back
    at itself (only "idle" does this in the asset data) - not when
    is_loop is true: short_rest/long_rest are also marked is_loop=true
    (their sprite keeps cycling while shown) but still have a distinct
    next_state_when_finished ("idle"), so is_loop alone cannot signal
    "never transition" - only the self-referencing next_state can.
    is_loop is used only by frame_index_for, to pick how the frame index
    wraps within whatever duration a state is shown for.
    """
    state = start_state
    remaining = elapsed_ms
    visited = set()
    while True:
        cfg = state_configs[state]
        if cfg.next_state == state:
            return state, remaining

        duration_ms = (cfg.frame_count / cfg.fps) * 1000 if cfg.fps else 0
        if remaining < duration_ms or state in visited:
            return state, remaining

        visited.add(state)
        remaining -= duration_ms
        state = cfg.next_state


def frame_index_for(cfg, ms_into_state):
    """Looping states wrap around; non-looping states freeze on their last
    frame once the sprite's own playback duration has elapsed (independent
    of how long the underlying game motion actually takes)."""
    if cfg.frame_count <= 0:
        return 0
    raw = int(ms_into_state / 1000 * cfg.fps)
    if cfg.is_loop:
        return raw % cfg.frame_count
    return min(raw, cfg.frame_count - 1)


def interpolate_position(start_cell, end_cell, start_time, arrival, clock, cell_size):
    if arrival <= start_time:
        t = 1.0
    else:
        t = (clock - start_time) / (arrival - start_time)
        t = max(0.0, min(1.0, t))

    start_row, start_col = start_cell
    end_row, end_col = end_cell
    x = (start_col + (end_col - start_col) * t) * cell_size
    y = (start_row + (end_row - start_row) * t) * cell_size
    return x, y


@dataclass(frozen=True)
class PieceView:
    token: str
    folder: str
    state: str
    frame_index: int
    x: float
    y: float


def compute_piece_views(snapshot, piece_configs, config):
    """Derives, for every occupied cell in the snapshot, which animation
    frame to draw and at what pixel position - purely from timestamps
    (the active moves/jumps and recent landings already on the snapshot),
    never from any stored per-piece state.
    """
    moves_by_start = {move.start: move for move in snapshot.moves}
    jumps_by_cell = {jump.cell: jump for jump in snapshot.jumps}
    arrivals_by_cell = {arrival.cell: arrival for arrival in snapshot.recent_arrivals}

    clock = snapshot.clock
    cell_size = config.CELL_SIZE
    views = []

    for row, row_tokens in enumerate(snapshot.cells):
        for col, token in enumerate(row_tokens):
            if token == config.EMPTY_CELL:
                continue

            cell = (row, col)
            folder = token_to_folder(token)
            state_configs = piece_configs[folder]

            move = moves_by_start.get(cell)
            jump = jumps_by_cell.get(cell)
            arrival = arrivals_by_cell.get(cell)

            if move is not None and move.piece == token:
                distance = max(abs(move.end[0] - move.start[0]), abs(move.end[1] - move.start[1]))
                start_time = move.arrival - distance * config.MOVE_DURATION
                state = "move"
                x, y = interpolate_position(move.start, move.end, start_time, move.arrival, clock, cell_size)
                frame_index = frame_index_for(state_configs[state], clock - start_time)
            elif jump is not None and jump.piece == token:
                start_time = jump.end_time - config.JUMP_DURATION
                state, ms_into_state = resolve_state_chain(state_configs, "jump", clock - start_time)
                x, y = col * cell_size, row * cell_size
                frame_index = frame_index_for(state_configs[state], ms_into_state)
            elif arrival is not None and arrival.piece == token:
                start_state = "long_rest" if arrival.kind == "move" else "short_rest"
                state, ms_into_state = resolve_state_chain(state_configs, start_state, clock - arrival.at)
                x, y = col * cell_size, row * cell_size
                frame_index = frame_index_for(state_configs[state], ms_into_state)
            else:
                state = "idle"
                x, y = col * cell_size, row * cell_size
                frame_index = frame_index_for(state_configs[state], clock)

            views.append(PieceView(token=token, folder=folder, state=state, frame_index=frame_index, x=x, y=y))

    return views
