"""
俄罗斯方块 (Tetris) - Python + Pygame 实现
操作说明：
  ← →    左右移动
  ↑       旋转方块
  ↓       加速下落
  空格     直接落到底部
  R       游戏结束后重新开始
  ESC     退出游戏
"""

import pygame
import random
import sys

# ============== 常量配置 ==============
CELL_SIZE = 30          # 每个格子的像素大小
COLS = 10               # 列数
ROWS = 20               # 行数
SIDEBAR_WIDTH = 200     # 侧边栏宽度
SCREEN_WIDTH = CELL_SIZE * COLS + SIDEBAR_WIDTH
SCREEN_HEIGHT = CELL_SIZE * ROWS
FPS = 60

# 颜色定义
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (40, 40, 40)
DARK_GRAY = (80, 80, 80)
BG_COLOR = (20, 20, 30)
GRID_COLOR = (40, 40, 55)
SIDEBAR_BG = (30, 30, 45)

# 7种标准方块的形状定义（每种有4个旋转状态）
# 使用相对坐标表示
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
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    'L': [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}

# 方块颜色（对应每种方块）
SHAPE_COLORS = {
    'I': (0, 240, 240),
    'O': (240, 240, 0),
    'T': (160, 0, 240),
    'S': (0, 240, 0),
    'Z': (240, 0, 0),
    'J': (0, 0, 240),
    'L': (240, 160, 0),
}

# 消行得分（1/2/3/4行）
LINE_SCORES = {1: 100, 2: 300, 3: 500, 4: 800}


class Piece:
    """表示一个正在下落的方块"""
    def __init__(self, shape_name=None):
        if shape_name is None:
            shape_name = random.choice(list(SHAPES.keys()))
        self.shape_name = shape_name
        self.rotation = 0
        self.color = SHAPE_COLORS[shape_name]
        # 初始位置：顶部居中
        self.x = COLS // 2 - 2
        self.y = 0

    def get_cells(self, rotation=None, offset_x=0, offset_y=0):
        """获取当前方块占据的所有格子坐标"""
        if rotation is None:
            rotation = self.rotation
        cells = SHAPES[self.shape_name][rotation]
        return [(x + self.x + offset_x, y + self.y + offset_y) for x, y in cells]

    def rotated_cells(self, direction=1, offset_x=0, offset_y=0):
        """获取旋转后的格子坐标（不实际旋转，用于碰撞检测）"""
        new_rotation = (self.rotation + direction) % 4
        cells = SHAPES[self.shape_name][new_rotation]
        return [(x + self.x + offset_x, y + self.y + offset_y) for x, y in cells]


class TetrisGame:
    """俄罗斯方块游戏主类"""
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("俄罗斯方块 Tetris")
        self.clock = pygame.time.Clock()
        # 字体兼容：尝试加载中文字体，失败则回退默认
        self.font_large = None
        for name in ["SimHei", "Microsoft YaHei", "PingFang SC"]:
            try:
                self.font_large = pygame.font.SysFont(name, 36, bold=True)
                self.font_medium = pygame.font.SysFont(name, 24)
                self.font_small = pygame.font.SysFont(name, 18)
                break
            except Exception:
                continue
        if self.font_large is None:
            self.font_large = pygame.font.Font(None, 36)
            self.font_medium = pygame.font.Font(None, 24)
            self.font_small = pygame.font.Font(None, 18)
        self.reset_game()

    def reset_game(self):
        """重置游戏状态"""
        # 游戏面板（二维数组，0=空，其他=颜色）
        self.board = [[None for _ in range(COLS)] for _ in range(ROWS)]
        self.score = 0
        self.level = 1
        self.lines_cleared = 0
        self.game_over = False
        self.paused = False

        # 当前方块和下一个方块
        self.current_piece = Piece()
        self.next_piece = Piece()

        # 下落计时器
        self.fall_timer = 0
        self.fall_speed = 800  # 毫秒（随等级降低）

        # 消行动画
        self.clearing_rows = []
        self.clear_animation_timer = 0

    def is_valid_position(self, cells):
        """检查一组格子坐标是否都在合法位置且不与已有方块重叠"""
        for x, y in cells:
            if x < 0 or x >= COLS or y >= ROWS:
                return False
            if y >= 0 and self.board[y][x] is not None:
                return False
        return True

    def lock_piece(self):
        """将当前方块锁定到面板上"""
        for x, y in self.current_piece.get_cells():
            if 0 <= y < ROWS and 0 <= x < COLS:
                self.board[y][x] = self.current_piece.color
        # 检查消行
        self.check_lines()
        # 生成新方块
        self.current_piece = self.next_piece
        self.next_piece = Piece()
        # 检查游戏是否结束
        if not self.is_valid_position(self.current_piece.get_cells()):
            self.game_over = True

    def check_lines(self):
        """检查并消除满行"""
        full_rows = []
        for y in range(ROWS):
            if all(cell is not None for cell in self.board[y]):
                full_rows.append(y)

        if full_rows:
            self.clearing_rows = full_rows
            self.clear_animation_timer = 300  # 300ms 动画时间
            # 计分
            lines = len(full_rows)
            self.lines_cleared += lines
            self.score += LINE_SCORES.get(lines, 0) * self.level
            # 升级（每消10行升一级）
            self.level = self.lines_cleared // 10 + 1
            self.fall_speed = max(100, 800 - (self.level - 1) * 70)

    def remove_cleared_lines(self):
        """移除已消除的行并下移上方行"""
        for y in sorted(self.clearing_rows, reverse=True):
            del self.board[y]
            self.board.insert(0, [None for _ in range(COLS)])
        self.clearing_rows = []

    def move_piece(self, dx, dy):
        """尝试移动当前方块"""
        new_cells = self.current_piece.get_cells(offset_x=dx, offset_y=dy)
        if self.is_valid_position(new_cells):
            self.current_piece.x += dx
            self.current_piece.y += dy
            return True
        return False

    def rotate_piece(self):
        """尝试旋转当前方块（含墙踢检测）"""
        # 尝试基本旋转
        new_cells = self.current_piece.rotated_cells()
        if self.is_valid_position(new_cells):
            self.current_piece.rotation = (self.current_piece.rotation + 1) % 4
            return True
        # 墙踢：尝试左右偏移1~2格
        for kick_x in [-1, 1, -2, 2]:
            new_cells = self.current_piece.rotated_cells(offset_x=kick_x)
            if self.is_valid_position(new_cells):
                self.current_piece.rotation = (self.current_piece.rotation + 1) % 4
                self.current_piece.x += kick_x
                return True
        return False

    def hard_drop(self):
        """直接落到底部"""
        drop_distance = 0
        while self.move_piece(0, 1):
            drop_distance += 1
        self.score += drop_distance * 2
        self.lock_piece()

    def get_ghost_position(self):
        """获取方块落到底部时的位置（幽灵方块）"""
        ghost_y = 0
        while True:
            new_cells = self.current_piece.get_cells(offset_y=ghost_y + 1)
            if self.is_valid_position(new_cells):
                ghost_y += 1
            else:
                break
        return [(x, y + ghost_y) for x, y in self.current_piece.get_cells()]

    def update(self, dt):
        """更新游戏状态"""
        if self.game_over or self.paused:
            return

        # 消行动画处理
        if self.clearing_rows:
            self.clear_animation_timer -= dt
            if self.clear_animation_timer <= 0:
                self.remove_cleared_lines()
            return

        # 自动下落
        self.fall_timer += dt
        if self.fall_timer >= self.fall_speed:
            self.fall_timer = 0
            if not self.move_piece(0, 1):
                self.lock_piece()

    def draw_block(self, x, y, color, alpha=255):
        """绘制一个带立体效果的方块"""
        rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
        if alpha < 255:
            s = pygame.Surface((CELL_SIZE, CELL_SIZE), pygame.SRCALPHA)
            s.fill((*color, alpha))
            self.screen.blit(s, rect.topleft)
        else:
            pygame.draw.rect(self.screen, color, rect)
            # 高光效果（左上亮边）
            highlight = tuple(min(c + 60, 255) for c in color)
            pygame.draw.line(self.screen, highlight, rect.topleft, rect.topright, 2)
            pygame.draw.line(self.screen, highlight, rect.topleft, rect.bottomleft, 2)
            # 阴影效果（右下暗边）
            shadow = tuple(max(c - 60, 0) for c in color)
            pygame.draw.line(self.screen, shadow, rect.bottomleft, rect.bottomright, 2)
            pygame.draw.line(self.screen, shadow, rect.topright, rect.bottomright, 2)

    def draw_board(self):
        """绘制游戏面板"""
        # 背景
        pygame.draw.rect(self.screen, BG_COLOR, (0, 0, CELL_SIZE * COLS, CELL_SIZE * ROWS))

        # 网格线
        for x in range(COLS + 1):
            pygame.draw.line(self.screen, GRID_COLOR,
                             (x * CELL_SIZE, 0), (x * CELL_SIZE, CELL_SIZE * ROWS))
        for y in range(ROWS + 1):
            pygame.draw.line(self.screen, GRID_COLOR,
                             (0, y * CELL_SIZE), (CELL_SIZE * COLS, y * CELL_SIZE))

        # 已锁定的方块
        for y in range(ROWS):
            for x in range(COLS):
                if self.board[y][x] is not None:
                    # 消行动画闪烁效果
                    if y in self.clearing_rows:
                        flash = int(self.clear_animation_timer / 50) % 2
                        if flash:
                            self.draw_block(x, y, WHITE)
                        else:
                            self.draw_block(x, y, self.board[y][x])
                    else:
                        self.draw_block(x, y, self.board[y][x])

    def draw_current_piece(self):
        """绘制当前下落的方块和幽灵方块"""
        if self.game_over:
            return

        # 幽灵方块（半透明预览落点）
        ghost_cells = self.get_ghost_position()
        for x, y in ghost_cells:
            if y >= 0:
                self.draw_block(x, y, self.current_piece.color, alpha=50)

        # 当前方块
        for x, y in self.current_piece.get_cells():
            if y >= 0:
                self.draw_block(x, y, self.current_piece.color)

    def draw_sidebar(self):
        """绘制侧边栏（分数、等级、下一个方块、操作说明）"""
        sidebar_x = CELL_SIZE * COLS
        pygame.draw.rect(self.screen, SIDEBAR_BG,
                         (sidebar_x, 0, SIDEBAR_WIDTH, SCREEN_HEIGHT))
        pygame.draw.line(self.screen, DARK_GRAY,
                         (sidebar_x, 0), (sidebar_x, SCREEN_HEIGHT), 2)

        cx = sidebar_x + SIDEBAR_WIDTH // 2
        y_offset = 20

        # 标题
        title = self.font_large.render("TETRIS", True, WHITE)
        self.screen.blit(title, (cx - title.get_width() // 2, y_offset))
        y_offset += 50

        # 分数
        score_label = self.font_small.render("SCORE", True, (180, 180, 200))
        self.screen.blit(score_label, (cx - score_label.get_width() // 2, y_offset))
        y_offset += 22
        score_val = self.font_medium.render(str(self.score), True, (0, 240, 120))
        self.screen.blit(score_val, (cx - score_val.get_width() // 2, y_offset))
        y_offset += 40

        # 等级
        level_label = self.font_small.render("LEVEL", True, (180, 180, 200))
        self.screen.blit(level_label, (cx - level_label.get_width() // 2, y_offset))
        y_offset += 22
        level_val = self.font_medium.render(str(self.level), True, (240, 200, 0))
        self.screen.blit(level_val, (cx - level_val.get_width() // 2, y_offset))
        y_offset += 40

        # 消行数
        lines_label = self.font_small.render("LINES", True, (180, 180, 200))
        self.screen.blit(lines_label, (cx - lines_label.get_width() // 2, y_offset))
        y_offset += 22
        lines_val = self.font_medium.render(str(self.lines_cleared), True, (100, 200, 240))
        self.screen.blit(lines_val, (cx - lines_val.get_width() // 2, y_offset))
        y_offset += 50

        # 下一个方块
        next_label = self.font_small.render("NEXT", True, (180, 180, 200))
        self.screen.blit(next_label, (cx - next_label.get_width() // 2, y_offset))
        y_offset += 25

        # 绘制下一个方块预览
        preview_size = 20
        preview_cells = SHAPES[self.next_piece.shape_name][0]
        # 计算方块边界以居中
        min_x = min(c[0] for c in preview_cells)
        max_x = max(c[0] for c in preview_cells)
        min_y = min(c[1] for c in preview_cells)
        max_y = max(c[1] for c in preview_cells)
        block_w = (max_x - min_x + 1) * preview_size
        block_h = (max_y - min_y + 1) * preview_size
        start_px = cx - block_w // 2
        start_py = y_offset

        for px, py in preview_cells:
            rect = pygame.Rect(
                start_px + (px - min_x) * preview_size,
                start_py + (py - min_y) * preview_size,
                preview_size, preview_size
            )
            color = self.next_piece.color
            pygame.draw.rect(self.screen, color, rect)
            highlight = tuple(min(c + 60, 255) for c in color)
            pygame.draw.line(self.screen, highlight, rect.topleft, rect.topright, 2)
            pygame.draw.line(self.screen, highlight, rect.topleft, rect.bottomleft, 2)
            shadow = tuple(max(c - 60, 0) for c in color)
            pygame.draw.line(self.screen, shadow, rect.bottomleft, rect.bottomright, 2)
            pygame.draw.line(self.screen, shadow, rect.topright, rect.bottomright, 2)

        y_offset += block_h + 40

        # 操作说明
        controls = [
            "← →  移动",
            "↑    旋转",
            "↓    加速",
            "空格  落底",
            "P    暂停",
            "R    重开",
            "ESC  退出",
        ]
        for text in controls:
            ctrl = self.font_small.render(text, True, (120, 120, 140))
            self.screen.blit(ctrl, (sidebar_x + 15, y_offset))
            y_offset += 22

    def draw_game_over(self):
        """绘制游戏结束画面"""
        # 半透明遮罩
        overlay = pygame.Surface((CELL_SIZE * COLS, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        game_over_text = self.font_large.render("GAME OVER", True, (240, 60, 60))
        cx = CELL_SIZE * COLS // 2
        self.screen.blit(game_over_text, (cx - game_over_text.get_width() // 2,
                                          SCREEN_HEIGHT // 2 - 40))

        restart_text = self.font_small.render("Press R to Restart", True, WHITE)
        self.screen.blit(restart_text, (cx - restart_text.get_width() // 2,
                                        SCREEN_HEIGHT // 2 + 20))

    def draw_paused(self):
        """绘制暂停画面"""
        overlay = pygame.Surface((CELL_SIZE * COLS, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        pause_text = self.font_large.render("PAUSED", True, (240, 200, 0))
        cx = CELL_SIZE * COLS // 2
        self.screen.blit(pause_text, (cx - pause_text.get_width() // 2,
                                      SCREEN_HEIGHT // 2 - 20))

    def run(self):
        """游戏主循环"""
        running = True
        while running:
            dt = self.clock.tick(FPS)

            # 事件处理
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_p and not self.game_over:
                        self.paused = not self.paused
                    elif event.key == pygame.K_r and self.game_over:
                        self.reset_game()
                    elif not self.game_over and not self.paused:
                        if event.key == pygame.K_LEFT:
                            self.move_piece(-1, 0)
                        elif event.key == pygame.K_RIGHT:
                            self.move_piece(1, 0)
                        elif event.key == pygame.K_DOWN:
                            if self.move_piece(0, 1):
                                self.score += 1
                            self.fall_timer = 0
                        elif event.key == pygame.K_UP:
                            self.rotate_piece()
                        elif event.key == pygame.K_SPACE:
                            self.hard_drop()

            # 更新
            self.update(dt)

            # 绘制
            self.screen.fill(BLACK)
            self.draw_board()
            self.draw_current_piece()
            self.draw_sidebar()

            if self.game_over:
                self.draw_game_over()
            elif self.paused:
                self.draw_paused()

            pygame.display.flip()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    game = TetrisGame()
    game.run()
