"""
俄罗斯方块 (Tetris) - Python + Pygame 实现
操作说明：
  ← →    左右移动
  ↑       旋转方块
  ↓       加速下落
  空格     直接落到底部（硬降）
  P       暂停/继续
  R       游戏结束后重新开始
  ESC     退出游戏
"""

import pygame
import random
import sys

# ──────────────── 常量设置 ────────────────
CELL_SIZE = 30          # 每个格子的像素大小
COLS = 10               # 游戏区列数
ROWS = 20               # 游戏区行数
SIDEBAR_WIDTH = 200     # 右侧信息栏宽度
SCREEN_WIDTH = CELL_SIZE * COLS + SIDEBAR_WIDTH
SCREEN_HEIGHT = CELL_SIZE * ROWS
FPS = 60

# 颜色定义
BLACK   = (0, 0, 0)
WHITE   = (255, 255, 255)
GRAY    = (40, 40, 40)
DARK    = (25, 25, 25)
BG_COLOR = (20, 20, 30)

# 7 种方块的顏色
COLORS = {
    'I': (0, 240, 240),
    'O': (240, 240, 0),
    'T': (160, 0, 240),
    'S': (0, 240, 0),
    'Z': (240, 0, 0),
    'J': (0, 0, 240),
    'L': (240, 160, 0),
}

# 7 种方块的形状定义（每种 4 个旋转状态）
# 用相对坐标表示，(col, row)
SHAPES = {
    'I': [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)],
    ],
    'O': [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
    ],
    'T': [
        [(0, 1), (1, 1), (2, 1), (1, 0)],
        [(1, 0), (1, 1), (1, 2), (2, 1)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (1, 1), (1, 2), (0, 1)],
    ],
    'S': [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
    ],
    'Z': [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)],
    ],
    'J': [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 0), (1, 0), (2, 0), (2, 1)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    'L': [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 0), (1, 0), (2, 0), (0, 1)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}


class Piece:
    """表示一个正在下落的方块"""
    def __init__(self, shape_name=None):
        if shape_name is None:
            shape_name = random.choice(list(SHAPES.keys()))
        self.shape_name = shape_name
        self.rotation = 0
        self.color = COLORS[shape_name]
        # 初始位置：顶部居中
        self.col = COLS // 2 - 2
        self.row = 0

    def cells(self):
        """返回当前方块占据的所有格子坐标 (col, row)"""
        return [(self.col + dc, self.row + dr)
                for dc, dr in SHAPES[self.shape_name][self.rotation]]

    def rotated_cells(self, direction=1):
        """返回旋转后方块占据的格子坐标"""
        new_rot = (self.rotation + direction) % 4
        return [(self.col + dc, self.row + dr)
                for dc, dr in SHAPES[self.shape_name][new_rot]]


class Board:
    """游戏面板"""
    def __init__(self):
        # grid[row][col] = None 或 颜色元组
        self.grid = [[None] * COLS for _ in range(ROWS)]

    def is_valid(self, cells):
        """检查一组格子坐标是否合法（在边界内且不重叠）"""
        for c, r in cells:
            if c < 0 or c >= COLS or r >= ROWS:
                return False
            if r >= 0 and self.grid[r][c] is not None:
                return False
        return True

    def lock(self, piece):
        """将方块锁定到网格中"""
        for c, r in piece.cells():
            if 0 <= r < ROWS:
                self.grid[r][c] = piece.color

    def clear_lines(self):
        """消除满行，返回消除的行数"""
        new_grid = [row for row in self.grid if any(cell is None for cell in row)]
        cleared = ROWS - len(new_grid)
        for _ in range(cleared):
            new_grid.insert(0, [None] * COLS)
        self.grid = new_grid
        return cleared


class Game:
    """游戏主逻辑"""
    def _load_font(self, size, bold=False):
        """尝试加载中文字体，失败则使用默认字体"""
        # 尝试常见中文字体路径
        font_paths = [
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/msyh.ttf",
            "C:/Windows/Fonts/simsun.ttc",
        ]
        for fp in font_paths:
            try:
                return pygame.font.Font(fp, size)
            except Exception:
                continue
        # 回退到默认字体
        font = pygame.font.Font(None, size)
        if bold:
            font.set_bold(True)
        return font

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Tetris - 俄罗斯方块")
        self.clock = pygame.time.Clock()
        self.font_big = self._load_font(36, bold=True)
        self.font_med = self._load_font(24)
        self.font_sm = self._load_font(18)
        self.reset()

    def reset(self):
        """重置游戏状态"""
        self.board = Board()
        self.bag = []
        self.current = self._next_piece()
        self.next_piece = self._next_piece()
        self.score = 0
        self.lines = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.drop_interval = 1000  # 毫秒
        self.last_drop = pygame.time.get_ticks()
        # 用于延迟自动重复（DAS）
        self.das_delay = 170   # 首次触发延迟 ms
        self.das_repeat = 50   # 重复间隔 ms
        self.das_dir = 0
        self.das_time = 0

    def _fill_bag(self):
        """7-bag 随机生成器，保证每 7 个一组"""
        bag = list(SHAPES.keys())
        random.shuffle(bag)
        self.bag = bag

    def _next_piece(self):
        if not self.bag:
            self._fill_bag()
        return Piece(self.bag.pop())

    def drop_speed(self):
        """根据等级计算下落间隔"""
        # 等级越高速度越快
        return max(100, 1000 - (self.level - 1) * 80)

    def move(self, dc, dr):
        """尝试移动当前方块，成功返回 True"""
        self.current.col += dc
        self.current.row += dr
        if self.board.is_valid(self.current.cells()):
            return True
        # 移动失败则回退
        self.current.col -= dc
        self.current.row -= dr
        return False

    def rotate(self):
        """旋转当前方块（带简单墙踢）"""
        new_cells = self.current.rotated_cells()
        if self.board.is_valid(new_cells):
            self.current.rotation = (self.current.rotation + 1) % 4
            return
        # 简单墙踢：尝试左右偏移 1~2 格
        for offset in [1, -1, 2, -2]:
            self.current.col += offset
            new_cells = self.current.rotated_cells()
            if self.board.is_valid(new_cells):
                self.current.rotation = (self.current.rotation + 1) % 4
                return
            self.current.col -= offset

    def hard_drop(self):
        """直接落到底部"""
        drop_rows = 0
        while self.move(0, 1):
            drop_rows += 1
        self.score += drop_rows * 2
        self._lock_and_next()

    def _lock_and_next(self):
        """锁定当前方块，生成下一个"""
        self.board.lock(self.current)
        cleared = self.board.clear_lines()
        # 计分：1行=100, 2行=300, 3行=500, 4行=800
        score_table = {0: 0, 1: 100, 2: 300, 3: 500, 4: 800}
        self.score += score_table.get(cleared, 800) * self.level
        self.lines += cleared
        self.level = self.lines // 10 + 1
        self.drop_interval = self.drop_speed()

        # 生成新方块
        self.current = self.next_piece
        self.next_piece = self._next_piece()

        # 检查游戏结束
        if not self.board.is_valid(self.current.cells()):
            self.game_over = True

    def get_ghost_cells(self):
        """计算幽灵方块（投影）的位置"""
        ghost_row = self.current.row
        while True:
            ghost_row += 1
            cells = [(self.current.col + dc, ghost_row + dr)
                     for dc, dr in SHAPES[self.current.shape_name][self.current.rotation]]
            if not self.board.is_valid(cells):
                ghost_row -= 1
                break
        return [(self.current.col + dc, ghost_row + dr)
                for dc, dr in SHAPES[self.current.shape_name][self.current.rotation]]

    def update(self):
        """游戏逻辑更新"""
        if self.game_over or self.paused:
            return
        now = pygame.time.get_ticks()
        if now - self.last_drop >= self.drop_interval:
            self.last_drop = now
            if not self.move(0, 1):
                self._lock_and_next()

    def handle_events(self):
        """处理输入事件"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                if self.game_over:
                    if event.key == pygame.K_r:
                        self.reset()
                    continue
                if event.key == pygame.K_p:
                    self.paused = not self.paused
                    continue
                if self.paused:
                    continue
                if event.key == pygame.K_LEFT:
                    self.move(-1, 0)
                    self.das_dir = -1
                    self.das_time = pygame.time.get_ticks()
                elif event.key == pygame.K_RIGHT:
                    self.move(1, 0)
                    self.das_dir = 1
                    self.das_time = pygame.time.get_ticks()
                elif event.key == pygame.K_DOWN:
                    if self.move(0, 1):
                        self.score += 1
                elif event.key == pygame.K_UP:
                    self.rotate()
                elif event.key == pygame.K_SPACE:
                    self.hard_drop()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                    self.das_dir = 0
        # DAS 自动重复
        if self.das_dir != 0 and not self.paused and not self.game_over:
            now = pygame.time.get_ticks()
            elapsed = now - self.das_time
            if elapsed > self.das_delay:
                repeats = (elapsed - self.das_delay) // self.das_repeat
                if repeats > 0:
                    self.move(self.das_dir, 0)
                    self.das_time = now - (elapsed - self.das_delay) % self.das_repeat
        return True

    def draw_block(self, col, row, color, alpha=255):
        """绘制一个方块格子"""
        x = col * CELL_SIZE
        y = row * CELL_SIZE
        rect = pygame.Rect(x, y, CELL_SIZE, CELL_SIZE)
        if alpha < 255:
            s = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
            s.fill((*color, alpha))
            self.screen.blit(s, (x, y))
        else:
            pygame.draw.rect(self.screen, color, rect)
        # 高光效果
        highlight = tuple(min(c + 50, 255) for c in color)
        shadow = tuple(max(c - 60, 0) for c in color)
        pygame.draw.line(self.screen, highlight, (x, y), (x + CELL_SIZE - 1, y))
        pygame.draw.line(self.screen, highlight, (x, y), (x, y + CELL_SIZE - 1))
        pygame.draw.line(self.screen, shadow, (x + CELL_SIZE - 1, y), (x + CELL_SIZE - 1, y + CELL_SIZE - 1))
        pygame.draw.line(self.screen, shadow, (x, y + CELL_SIZE - 1), (x + CELL_SIZE - 1, y + CELL_SIZE - 1))

    def draw_grid(self):
        """绘制游戏区网格线"""
        for r in range(ROWS):
            for c in range(COLS):
                rect = pygame.Rect(c * CELL_SIZE, r * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(self.screen, GRAY, rect, 1)

    def draw_board(self):
        """绘制已锁定的方块"""
        for r in range(ROWS):
            for c in range(COLS):
                if self.board.grid[r][c] is not None:
                    self.draw_block(c, r, self.board.grid[r][c])

    def draw_current_piece(self):
        """绘制当前下落的方块"""
        for c, r in self.current.cells():
            if r >= 0:
                self.draw_block(c, r, self.current.color)

    def draw_ghost(self):
        """绘制幽灵方块（投影）"""
        for c, r in self.get_ghost_cells():
            if r >= 0:
                self.draw_block(c, r, self.current.color, alpha=60)

    def draw_sidebar(self):
        """绘制右侧信息栏"""
        x_offset = CELL_SIZE * COLS + 15
        # 分隔线
        pygame.draw.line(self.screen, GRAY,
                         (CELL_SIZE * COLS, 0),
                         (CELL_SIZE * COLS, SCREEN_HEIGHT), 2)

        # 标题
        title = self.font_big.render("俄罗斯方块", True, WHITE)
        self.screen.blit(title, (x_offset, 15))

        # 分数
        y = 70
        self._draw_label("分数", self.score, x_offset, y)
        y += 60
        self._draw_label("行数", self.lines, x_offset, y)
        y += 60
        self._draw_label("等级", self.level, x_offset, y)

        # 下一个方块预览
        y += 70
        label = self.font_med.render("下一个", True, WHITE)
        self.screen.blit(label, (x_offset, y))
        y += 35
        preview_size = 20
        for dc, dr in SHAPES[self.next_piece.shape_name][0]:
            px = x_offset + 10 + dc * preview_size
            py = y + dr * preview_size
            rect = pygame.Rect(px, py, preview_size, preview_size)
            pygame.draw.rect(self.screen, self.next_piece.color, rect)
            pygame.draw.rect(self.screen, GRAY, rect, 1)

        # 操作说明
        y += 120
        instructions = [
            "← →  移动",
            "↑    旋转",
            "↓    加速",
            "空格  硬降",
            "P    暂停",
            "R    重开",
            "ESC  退出",
        ]
        for line in instructions:
            txt = self.font_sm.render(line, True, (180, 180, 180))
            self.screen.blit(txt, (x_offset, y))
            y += 22

    def _draw_label(self, text, value, x, y):
        label = self.font_med.render(text, True, (180, 180, 180))
        val = self.font_med.render(str(value), True, WHITE)
        self.screen.blit(label, (x, y))
        self.screen.blit(val, (x, y + 28))

    def draw_overlay(self, text, sub_text=""):
        """绘制半透明覆盖层（暂停/游戏结束）"""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        try:
            txt = self.font_big.render(text, True, WHITE)
        except Exception:
            txt = self.font_big.render("GAME OVER" if "结束" in text else "PAUSED", True, WHITE)
        rect = txt.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 20))
        self.screen.blit(txt, rect)
        if sub_text:
            try:
                sub = self.font_med.render(sub_text, True, (200, 200, 200))
            except Exception:
                sub = self.font_med.render("Press R to restart" if "R" in sub_text else "Press P to continue", True, (200, 200, 200))
            rect2 = sub.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 25))
            self.screen.blit(sub, rect2)

    def draw(self):
        """绘制整个画面"""
        self.screen.fill(BG_COLOR)
        self.draw_grid()
        self.draw_board()
        if not self.game_over:
            self.draw_ghost()
            self.draw_current_piece()
        self.draw_sidebar()
        if self.paused:
            self.draw_overlay("暂停中", "按 P 继续")
        if self.game_over:
            self.draw_overlay("游戏结束", f"得分: {self.score}  按 R 重新开始")
        pygame.display.flip()

    def run(self):
        """游戏主循环"""
        running = True
        while running:
            running = self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    game = Game()
    game.run()
