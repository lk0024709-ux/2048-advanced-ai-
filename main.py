from __future__ import annotations

import json
import math
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Dict, List, Optional, Sequence, Tuple

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    DictProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.togglebutton import ToggleButton

KV = r'''
#:import dp kivy.metrics.dp

<TileLabel@Label>:
    val: 0
    scale: 1.0
    color_bg: (0.93, 0.89, 0.85, 1)
    canvas.before:
        PushMatrix
        Scale:
            origin: self.center
            x: self.scale
            y: self.scale
            z: 1
        Color:
            rgba: self.color_bg
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(6), dp(6), dp(6), dp(6)]
    canvas.after:
        PopMatrix
    font_size: min(self.width, self.height) * (0.35 if len(self.text) < 4 else 0.28)
    bold: True

<BoardWidget>:
    canvas.before:
        Color:
            rgba: (0.73, 0.68, 0.63, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8), dp(8), dp(8), dp(8)]

<RootWidget>:
    orientation: 'vertical'
    padding: dp(12)
    spacing: dp(10)

    BoxLayout:
        size_hint_y: None
        height: dp(72)
        spacing: dp(10)

        Label:
            text: '2048'
            bold: True
            color: (0.47, 0.43, 0.4, 1)
            font_size: dp(42)
            size_hint_x: 0.35

        BoxLayout:
            orientation: 'vertical'
            padding: dp(8)
            canvas.before:
                Color:
                    rgba: (0.73, 0.68, 0.63, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(5), dp(5), dp(5), dp(5)]
            Label:
                text: 'Score'
                font_size: dp(12)
                color: (0.93, 0.89, 0.85, 1)
            Label:
                text: str(root.score)
                bold: True
                color: (1, 1, 1, 1)

        BoxLayout:
            orientation: 'vertical'
            padding: dp(8)
            canvas.before:
                Color:
                    rgba: (0.73, 0.68, 0.63, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(5), dp(5), dp(5), dp(5)]
            Label:
                text: 'Best'
                font_size: dp(12)
                color: (0.93, 0.89, 0.85, 1)
            Label:
                text: str(root.best_score)
                bold: True
                color: (1, 1, 1, 1)

    BoxLayout:
        size_hint_y: None
        height: dp(40)
        spacing: dp(8)

        ToggleButton:
            id: ai_toggle
            text: 'AI Auto-Play: ON' if self.state == 'down' else 'AI Auto-Play: OFF'
            state: 'normal'
            on_state: root.on_ai_toggle(self.state == 'down')
        Label:
            text: root.status_text
            color: (0.47, 0.43, 0.4, 1)

        Label:
            size_hint_x: None
            width: dp(10)

        kivy.uix.button.Button:
            text: 'New Game'
            size_hint_x: None
            width: dp(120)
            on_release: root.new_game()

    FloatLayout:
        BoardWidget:
            id: board
            size_hint: None, None
            size: min(self.parent.width, self.parent.height), min(self.parent.width, self.parent.height)
            pos_hint: {'center_x': 0.5, 'center_y': 0.5}

            GridLayout:
                id: grid
                cols: 4
                rows: 4
                spacing: dp(8)
                padding: dp(8)
                size_hint: 1, 1

                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
                TileLabel:
'''

TILE_COLORS: Dict[int, Tuple[float, float, float, float]] = {
    0: (0.93, 0.89, 0.85, 1),
    2: (0.93, 0.89, 0.85, 1),
    4: (0.93, 0.88, 0.78, 1),
    8: (0.95, 0.69, 0.47, 1),
    16: (0.96, 0.58, 0.39, 1),
    32: (0.96, 0.49, 0.37, 1),
    64: (0.96, 0.37, 0.23, 1),
    128: (0.93, 0.81, 0.45, 1),
    256: (0.93, 0.8, 0.38, 1),
    512: (0.93, 0.78, 0.31, 1),
    1024: (0.93, 0.77, 0.25, 1),
    2048: (0.93, 0.76, 0.19, 1),
    4096: (0.24, 0.23, 0.2, 1),
    8192: (0.2, 0.19, 0.17, 1),
    16384: (0.17, 0.16, 0.14, 1),
    32768: (0.14, 0.13, 0.12, 1),
    65536: (0.11, 0.1, 0.09, 1),
}

MOVES: Dict[str, Tuple[int, int, int, int]] = {
    "left": (0, 1, 2, 3),
    "right": (3, 2, 1, 0),
    "up": (0, 4, 8, 12),
    "down": (12, 8, 4, 0),
}


@dataclass
class MoveResult:
    board: Tuple[int, ...]
    score_gain: int
    moved: bool
    merged_positions: List[int]


class GameEngine:
    def __init__(self) -> None:
        self.board: List[int] = [0] * 16
        self.score = 0
        self.won = False
        self.over = False
        self.reset()

    def reset(self) -> None:
        self.board = [0] * 16
        self.score = 0
        self.won = False
        self.over = False
        self.spawn_tile()
        self.spawn_tile()

    def spawn_tile(self) -> bool:
        empties = [i for i, v in enumerate(self.board) if v == 0]
        if not empties:
            return False
        idx = random.choice(empties)
        self.board[idx] = 4 if random.random() < 0.1 else 2
        return True

    @staticmethod
    def _compress_line(values: Sequence[int]) -> Tuple[List[int], int, bool, List[int]]:
        raw = [v for v in values if v]
        merged: List[int] = []
        score_gain = 0
        i = 0
        merged_indices: List[int] = []
        while i < len(raw):
            if i + 1 < len(raw) and raw[i] == raw[i + 1]:
                nv = raw[i] * 2
                merged.append(nv)
                score_gain += nv
                merged_indices.append(len(merged) - 1)
                i += 2
            else:
                merged.append(raw[i])
                i += 1
        merged.extend([0] * (4 - len(merged)))
        moved = list(values) != merged
        return merged, score_gain, moved, merged_indices

    def simulate_move(self, board: Sequence[int], direction: str) -> MoveResult:
        new_board = list(board)
        total_gain = 0
        moved = False
        merged_abs: List[int] = []
        for r in range(4):
            idx = [m + r if direction in ("up", "down") else r * 4 + m for m in MOVES[direction]]
            line = [new_board[i] for i in idx]
            comp, gain, did_move, merged_rel = self._compress_line(line)
            if direction in ("right", "down"):
                comp = comp
            for k, i_board in enumerate(idx):
                old = new_board[i_board]
                new_board[i_board] = comp[k]
                if old != new_board[i_board]:
                    moved = True
            total_gain += gain
            merged_abs.extend(idx[mr] for mr in merged_rel)
            moved = moved or did_move
        return MoveResult(tuple(new_board), total_gain, moved, merged_abs)

    def move(self, direction: str) -> MoveResult:
        result = self.simulate_move(self.board, direction)
        if result.moved:
            self.board = list(result.board)
            self.score += result.score_gain
            self.won = any(v >= 2048 for v in self.board)
            self.spawn_tile()
            self.over = not self.has_moves(self.board)
        return result

    def has_moves(self, board: Sequence[int]) -> bool:
        if any(v == 0 for v in board):
            return True
        for direction in MOVES:
            if self.simulate_move(board, direction).moved:
                return True
        return False


class ExpectimaxAI:
    def __init__(self, engine: GameEngine, depth: int = 4) -> None:
        self.engine = engine
        self.depth = depth
        self.cache: Dict[Tuple[Tuple[int, ...], int, bool], float] = {}
        self.gradient = [
            65536, 32768, 16384, 8192,
            512, 1024, 2048, 4096,
            256, 128, 64, 32,
            2, 4, 8, 16,
        ]

    def choose_move(self, board: Sequence[int]) -> Optional[str]:
        best_move: Optional[str] = None
        best_score = float("-inf")
        btuple = tuple(board)
        for direction in MOVES:
            res = self.engine.simulate_move(btuple, direction)
            if not res.moved:
                continue
            score = self._expect_value(res.board, self.depth - 1)
            if score > best_score:
                best_score = score
                best_move = direction
        return best_move

    def _expect_value(self, board: Tuple[int, ...], depth: int) -> float:
        key = (board, depth, False)
        if key in self.cache:
            return self.cache[key]
        empties = [i for i, v in enumerate(board) if v == 0]
        if depth == 0 or not empties:
            v = self.evaluate(board)
            self.cache[key] = v
            return v
        value = 0.0
        p_cell = 1.0 / len(empties)
        for idx in empties:
            for tile, p_tile in ((2, 0.9), (4, 0.1)):
                nb = list(board)
                nb[idx] = tile
                value += p_cell * p_tile * self._max_value(tuple(nb), depth - 1)
        self.cache[key] = value
        return value

    def _max_value(self, board: Tuple[int, ...], depth: int) -> float:
        key = (board, depth, True)
        if key in self.cache:
            return self.cache[key]
        if depth == 0:
            v = self.evaluate(board)
            self.cache[key] = v
            return v
        candidates: List[float] = []
        for direction in MOVES:
            res = self.engine.simulate_move(board, direction)
            if res.moved:
                candidates.append(self._expect_value(res.board, depth - 1))
        if not candidates:
            v = self.evaluate(board)
            self.cache[key] = v
            return v
        v = max(candidates)
        self.cache[key] = v
        return v

    def evaluate(self, board: Tuple[int, ...]) -> float:
        max_tile = max(board)
        gradient_score = 0.0
        merge_potential = 0.0
        for i, v in enumerate(board):
            gradient_score += v * self.gradient[i]
            if i % 4 < 3 and v and v == board[i + 1]:
                merge_potential += v
            if i < 12 and v and v == board[i + 4]:
                merge_potential += v
        empty_count = sum(1 for v in board if v == 0)
        empty_bonus = math.log2(empty_count + 1) * 5000
        max_corner_bonus = 5000 if board[0] == max_tile else 0
        return gradient_score * 0.0001 + merge_potential * 2 + empty_bonus + max_corner_bonus


class BoardWidget(FloatLayout):
    pass


class RootWidget(BoxLayout):
    score = NumericProperty(0)
    best_score = NumericProperty(0)
    status_text = StringProperty("Play manually or enable AI")
    ai_enabled = BooleanProperty(False)
    tile_values = ListProperty([0] * 16)
    tile_widgets = ObjectProperty(None)
    tile_pos = DictProperty({})

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.engine = GameEngine()
        self.ai = ExpectimaxAI(self.engine)
        self.ai_queue: Queue[str] = Queue(maxsize=1)
        self.ai_thread: Optional[threading.Thread] = None
        self.best_score_path = Path("best_score.json")
        self.best_score = self._load_best()
        Clock.schedule_once(self._finish_init, 0)

    def _finish_init(self, *_args) -> None:
        grid = self.ids.grid
        self.tile_widgets = list(grid.children)[::-1]
        self.refresh_board([], [])
        Clock.schedule_interval(self.poll_ai_queue, 1 / 30)
        Clock.schedule_interval(self.ai_loop_tick, 0.05)

    def _load_best(self) -> int:
        try:
            data = json.loads(self.best_score_path.read_text())
            return int(data.get("best", 0))
        except Exception:
            return 0

    def _save_best(self) -> None:
        self.best_score_path.write_text(json.dumps({"best": self.best_score}))

    def on_ai_toggle(self, enabled: bool) -> None:
        self.ai_enabled = enabled
        self.status_text = "AI searching..." if enabled else "Manual mode"

    def new_game(self) -> None:
        self.engine.reset()
        self.score = 0
        self.status_text = "New game started"
        self.refresh_board([], [])

    def handle_move(self, direction: str) -> None:
        if self.engine.over:
            return
        result = self.engine.move(direction)
        if result.moved:
            self.score = self.engine.score
            if self.score > self.best_score:
                self.best_score = self.score
                self._save_best()
            self.refresh_board(result.merged_positions, [])
            if self.engine.won:
                self.status_text = "2048 reached!"
            elif self.engine.over:
                self.status_text = "Game over"

    def refresh_board(self, merged_positions: List[int], _new_tiles: List[int]) -> None:
        for i, lbl in enumerate(self.tile_widgets):
            val = self.engine.board[i]
            lbl.text = str(val) if val else ""
            lbl.color_bg = TILE_COLORS.get(val, TILE_COLORS[65536])
            lbl.color = (0.47, 0.43, 0.4, 1) if val <= 4 else (0.97, 0.96, 0.95, 1)
            if val and lbl.scale == 1.0 and lbl.text:
                lbl.scale = 0.0
                Animation(scale=1.0, duration=0.08, t="out_back").start(lbl)
            if i in merged_positions:
                Animation.cancel_all(lbl)
                seq = Animation(scale=1.2, duration=0.06) + Animation(scale=1.0, duration=0.06)
                seq.start(lbl)

    def ai_loop_tick(self, _dt: float) -> None:
        if not self.ai_enabled or self.engine.over:
            return
        if self.ai_thread and self.ai_thread.is_alive():
            return
        board = tuple(self.engine.board)

        def worker() -> None:
            move = self.ai.choose_move(board)
            if move:
                try:
                    self.ai_queue.put_nowait(move)
                except Exception:
                    pass

        self.ai_thread = threading.Thread(target=worker, daemon=True)
        self.ai_thread.start()

    def poll_ai_queue(self, _dt: float) -> None:
        try:
            move = self.ai_queue.get_nowait()
        except Empty:
            return
        self.handle_move(move)


class Game2048App(App):
    def build(self) -> RootWidget:
        Window.minimum_width = 420
        Window.minimum_height = 560
        Window.bind(on_key_down=self.on_key_down)
        Builder.load_string(KV)
        return RootWidget()

    def on_key_down(self, _window, key, _scancode, _codepoint, _modifiers) -> bool:
        mapping = {273: "up", 274: "down", 276: "left", 275: "right"}
        if key in mapping:
            self.root.handle_move(mapping[key])
            return True
        return False


if __name__ == "__main__":
    random.seed(time.time())
    Game2048App().run()
