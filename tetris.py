"""
俄罗斯方块 - Python + Tkinter 实现
操作说明：
  ← →    左右移动
  ↑       旋转方块
  ↓       加速下落
  空格    直接落到底部
  P       暂停/继续
  R       游戏结束后重新开始
"""

import tkinter as tk
import random

# ── 常量 ──────────────────────────────────────────────
COLS = 10          # 列数
ROWS = 20          # 行数
CELL = 30          # 每格像素
SPEED_INIT = 500   # 初始下落间隔(ms)
SPEED_MIN = 80     # 最快下落间隔(ms)
SPEED_STEP = 40    # 每升一级减少的毫秒

# 7 种方块的形状定义（每种 4 个旋转状态）
SHAPES = {
    'I': [
        [(0,0),(1,0),(2,0),(3,0)],
        [(0,0),(0,1),(0,2),(0,3)],
        [(0,0),(1,0),(2,0),(3,0)],
        [(0,0),(0,1),(0,2),(0,3)],
    ],
    'O': [
        [(0,0),(1,0),(0,1),(1,1)],
        [(0,0),(1,0),(0,1),(1,1)],
        [(0,0),(1,0),(0,1),(1,1)],
        [(0,0),(1,0),(0,1),(1,1)],
    ],
    'T': [
        [(0,0),(1,0),(2,0),(1,1)],
        [(0,0),(0,1),(0,2),(1,1)],
        [(1,0),(0,1),(1,1),(2,1)],
        [(1,0),(1,1),(1,2),(0,1)],
    ],
    'S': [
        [(1,0),(2,0),(0,1),(1,1)],
        [(0,0),(0,1),(1,1),(1,2)],
        [(1,0),(2,0),(0,1),(1,1)],
        [(0,0),(0,1),(1,1),(1,2)],
    ],
    'Z': [
        [(0,0),(1,0),(1,1),(2,1)],
        [(1,0),(0,1),(1,1),(0,2)],
        [(0,0),(1,0),(1,1),(2,1)],
        [(1,0),(0,1),(1,1),(0,2)],
    ],
    'J': [
        [(0,0),(0,1),(1,1),(2,1)],
        [(0,0),(1,0),(0,1),(0,2)],
        [(0,0),(1,0),(2,0),(2,1)],
        [(1,0),(1,1),(0,2),(1,2)],
    ],
    'L': [
        [(2,0),(0,1),(1,1),(2,1)],
        [(0,0),(0,1),(0,2),(1,2)],
        [(0,0),(1,0),(2,0),(0,1)],
        [(0,0),(1,0),(1,1),(1,2)],
    ],
}

COLORS = {
    'I': '#00f0f0',  # 青
    'O': '#f0f000',  # 黄
    'T': '#a000f0',  # 紫
    'S': '#00f000',  # 绿
    'Z': '#f00000',  # 红
    'J': '#0000f0',  # 蓝
    'L': '#f0a000',  # 橙
}

BG_COLOR = '#1a1a2e'
GRID_COLOR = '#16213e'
GHOST_COLOR = '#3a3a5e'


# ── 游戏逻辑 ──────────────────────────────────────────
class Tetris:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('俄罗斯方块')
        self.root.resizable(False, False)

        # 主容器
        frame = tk.Frame(self.root, bg='#0f3460', padx=10, pady=10)
        frame.pack()

        # 画布
        self.canvas = tk.Canvas(
            frame, width=COLS * CELL, height=ROWS * CELL,
            bg=BG_COLOR, highlightthickness=0
        )
        self.canvas.grid(row=0, column=0, rowspan=9)

        # 右侧信息面板
        info_frame = tk.Frame(frame, bg='#0f3460', padx=10)
        info_frame.grid(row=0, column=1, sticky='n')

        self._make_label(info_frame, '下一个', row=0)
        self.next_canvas = tk.Canvas(
            info_frame, width=4 * CELL, height=4 * CELL,
            bg=BG_COLOR, highlightthickness=0
        )
        self.next_canvas.grid(row=1, column=0, pady=(0, 15))

        self._make_label(info_frame, '分数', row=2)
        self.score_var = tk.StringVar(value='0')
        tk.Label(info_frame, textvariable=self.score_var, font=('Consolas', 18, 'bold'),
                 fg='#e94560', bg='#0f3460').grid(row=3, column=0, pady=(0, 15))

        self._make_label(info_frame, '等级', row=4)
        self.level_var = tk.StringVar(value='1')
        tk.Label(info_frame, textvariable=self.level_var, font=('Consolas', 18, 'bold'),
                 fg='#e94560', bg='#0f3460').grid(row=5, column=0, pady=(0, 15))

        self._make_label(info_frame, '消行', row=6)
        self.lines_var = tk.StringVar(value='0')
        tk.Label(info_frame, textvariable=self.lines_var, font=('Consolas', 18, 'bold'),
                 fg='#e94560', bg='#0f3460').grid(row=7, column=0, pady=(0, 15))

        # 操作提示
        tips = tk.Label(info_frame, text='← → 移动\n↑ 旋转\n↓ 加速\n空格 硬降\nP 暂停\nR 重开',
                        font=('Microsoft YaHei', 9), fg='#a0a0c0', bg='#0f3460',
                        justify='left')
        tips.grid(row=8, column=0, pady=(20, 0))

        # 游戏状态
        self.board = [[None] * COLS for _ in range(ROWS)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.bag = []

        # 当前方块
        self.cur_name = None
        self.cur_rot = 0
        self.cur_x = 0
        self.cur_y = 0
        self.next_name = None

        # 绑定按键
        self.root.bind('<KeyPress>', self.on_key)

        # 开始
        self._spawn_next()
        self._spawn_next()
        self._tick()
        self._draw()

        self.root.mainloop()

    # ── UI 辅助 ──
    def _make_label(self, parent, text, row):
        tk.Label(parent, text=text, font=('Microsoft YaHei', 11, 'bold'),
                 fg='#e0e0e0', bg='#0f3460').grid(row=row, column=0, pady=(10, 2))

    # ── 方块生成（7-bag 随机） ──
    def _next_from_bag(self):
        if not self.bag:
            self.bag = list(SHAPES.keys())
            random.shuffle(self.bag)
        return self.bag.pop()

    def _spawn_next(self):
        if self.next_name is None:
            self.next_name = self._next_from_bag()
        self.cur_name = self.next_name
        self.next_name = self._next_from_bag()
        self.cur_rot = 0
        # 计算方块宽度，居中放置
        cells = SHAPES[self.cur_name][0]
        min_x = min(c for c, r in cells)
        max_x = max(c for c, r in cells)
        w = max_x - min_x + 1
        self.cur_x = (COLS - w) // 2 - min_x
        self.cur_y = 0
        # 检测是否能放置，不能则游戏结束
        if not self._valid(self.cur_x, self.cur_y, self.cur_rot):
            self.game_over = True

    # ── 碰撞检测 ──
    def _cells(self, x, y, rot):
        return [(x + c, y + r) for c, r in SHAPES[self.cur_name][rot % len(SHAPES[self.cur_name])]]

    def _valid(self, x, y, rot):
        for cx, cy in self._cells(x, y, rot):
            if cx < 0 or cx >= COLS or cy >= ROWS:
                return False
            if cy >= 0 and self.board[cy][cx] is not None:
                return False
        return True

    # ── 操作 ──
    def _move(self, dx, dy):
        if self._valid(self.cur_x + dx, self.cur_y + dy, self.cur_rot):
            self.cur_x += dx
            self.cur_y += dy
            return True
        return False

    def _rotate(self):
        new_rot = (self.cur_rot + 1) % 4
        # 尝试原位和偏移（简单墙踢）
        for dx in [0, -1, 1, -2, 2]:
            if self._valid(self.cur_x + dx, self.cur_y, new_rot):
                self.cur_x += dx
                self.cur_rot = new_rot
                return

    def _hard_drop(self):
        while self._move(0, 1):
            self.score += 2
        self._lock()

    def _ghost_y(self):
        gy = self.cur_y
        while self._valid(self.cur_x, gy + 1, self.cur_rot):
            gy += 1
        return gy

    def _lock(self):
        for cx, cy in self._cells(self.cur_x, self.cur_y, self.cur_rot):
            if 0 <= cy < ROWS:
                self.board[cy][cx] = self.cur_name
        self._clear_lines()
        self._spawn_next()

    def _clear_lines(self):
        cleared = 0
        new_board = []
        for row in self.board:
            if all(cell is not None for cell in row):
                cleared += 1
            else:
                new_board.append(row)
        for _ in range(cleared):
            new_board.insert(0, [None] * COLS)
        self.board = new_board
        if cleared:
            # 经典计分：1→100, 2→300, 3→500, 4→800
            points = [0, 100, 300, 500, 800]
            self.score += points[min(cleared, 4)] * self.level
            self.lines += cleared
            self.level = self.lines // 10 + 1

    # ── 游戏循环 ──
    def _tick(self):
        if not self.game_over and not self.paused:
            if not self._move(0, 1):
                self._lock()
            self._draw()
            speed = max(SPEED_MIN, SPEED_INIT - (self.level - 1) * SPEED_STEP)
            self.root.after(speed, self._tick)

    # ── 按键处理 ──
    def on_key(self, event):
        key = event.keysym
        if self.game_over:
            if key.lower() == 'r':
                self._restart()
            return
        if key.lower() == 'p':
            self.paused = not self.paused
            if not self.paused:
                self._tick()
            self._draw()
            return
        if self.paused:
            return
        if key == 'Left':
            self._move(-1, 0)
        elif key == 'Right':
            self._move(1, 0)
        elif key == 'Down':
            if self._move(0, 1):
                self.score += 1
        elif key == 'Up':
            self._rotate()
        elif key == 'space':
            self._hard_drop()
        self._draw()

    def _restart(self):
        self.board = [[None] * COLS for _ in range(ROWS)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.bag = []
        self.next_name = None
        self._spawn_next()
        self._spawn_next()
        self._tick()
        self._draw()

    # ── 绘制 ──
    def _draw(self):
        c = self.canvas
        c.delete('all')

        # 网格线
        for x in range(COLS + 1):
            c.create_line(x * CELL, 0, x * CELL, ROWS * CELL, fill=GRID_COLOR)
        for y in range(ROWS + 1):
            c.create_line(0, y * CELL, COLS * CELL, y * CELL, fill=GRID_COLOR)

        # 已锁定的方块
        for y in range(ROWS):
            for x in range(COLS):
                if self.board[y][x]:
                    self._draw_cell(c, x, y, COLORS[self.board[y][x]])

        if not self.game_over:
            # 幽灵（投影）
            gy = self._ghost_y()
            for cx, cy in self._cells(self.cur_x, gy, self.cur_rot):
                if 0 <= cy < ROWS:
                    self._draw_cell(c, cx, cy, GHOST_COLOR, ghost=True)

            # 当前方块
            for cx, cy in self._cells(self.cur_x, self.cur_y, self.cur_rot):
                if 0 <= cy < ROWS:
                    self._draw_cell(c, cx, cy, COLORS[self.cur_name])

        # 更新信息
        self.score_var.set(str(self.score))
        self.level_var.set(str(self.level))
        self.lines_var.set(str(self.lines))

        # 下一个方块预览
        nc = self.next_canvas
        nc.delete('all')
        if self.next_name:
            cells = SHAPES[self.next_name][0]
            min_c = min(c for c, r in cells)
            max_c = max(c for c, r in cells)
            min_r = min(r for c, r in cells)
            max_r = max(r for c, r in cells)
            w = max_c - min_c + 1
            h = max_r - min_r + 1
            ox = (4 * CELL - w * CELL) // 2
            oy = (4 * CELL - h * CELL) // 2
            for c, r in cells:
                x = ox + (c - min_c) * CELL
                y = oy + (r - min_r) * CELL
                nc.create_rectangle(x + 1, y + 1, x + CELL - 1, y + CELL - 1,
                                    fill=COLORS[self.next_name], outline='')
                # 高光
                nc.create_rectangle(x + 1, y + 1, x + CELL - 1, y + 4,
                                    fill='#ffffff', stipple='gray25', outline='')

        # 暂停 / 游戏结束 覆盖层
        if self.paused:
            c.create_rectangle(0, 0, COLS * CELL, ROWS * CELL, fill='#000000', stipple='gray50')
            c.create_text(COLS * CELL // 2, ROWS * CELL // 2, text='暂 停',
                          font=('Microsoft YaHei', 28, 'bold'), fill='#ffffff')
        elif self.game_over:
            c.create_rectangle(0, 0, COLS * CELL, ROWS * CELL, fill='#000000', stipple='gray50')
            c.create_text(COLS * CELL // 2, ROWS * CELL // 2 - 20, text='游戏结束',
                          font=('Microsoft YaHei', 28, 'bold'), fill='#e94560')
            c.create_text(COLS * CELL // 2, ROWS * CELL // 2 + 30, text=f'得分：{self.score}',
                          font=('Microsoft YaHei', 16), fill='#ffffff')
            c.create_text(COLS * CELL // 2, ROWS * CELL // 2 + 60, text='按 R 重新开始',
                          font=('Microsoft YaHei', 12), fill='#a0a0c0')

    def _draw_cell(self, canvas, x, y, color, ghost=False):
        px = x * CELL
        py = y * CELL
        if ghost:
            canvas.create_rectangle(px + 2, py + 2, px + CELL - 2, py + CELL - 2,
                                    outline=color, width=2, fill='')
        else:
            canvas.create_rectangle(px + 1, py + 1, px + CELL - 1, py + CELL - 1,
                                    fill=color, outline='')
            # 高光效果
            canvas.create_rectangle(px + 1, py + 1, px + CELL - 1, py + 5,
                                    fill='#ffffff', stipple='gray25', outline='')
            canvas.create_rectangle(px + 1, py + 1, px + 5, py + CELL - 1,
                                    fill='#ffffff', stipple='gray25', outline='')


if __name__ == '__main__':
    Tetris()
