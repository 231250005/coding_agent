import random

def guess_number_game():
    print("=" * 40)
    print("🎮 欢迎来到猜数字小游戏！")
    print("=" * 40)
    print("我已经想好了一个 1 到 100 之间的整数。")
    print("你能猜到它是什么吗？\n")

    secret_number = random.randint(1, 100)
    max_attempts = 7
    attempts = 0

    while attempts < max_attempts:
        remaining = max_attempts - attempts
        try:
            guess = int(input(f"请输入你的猜测（还剩 {remaining} 次机会）："))
        except ValueError:
            print("⚠️ 请输入一个有效的整数！\n")
            continue

        attempts += 1

        if guess < 1 or guess > 100:
            print("⚠️ 请输入 1 到 100 之间的数字！\n")
            attempts -= 1  # 不算一次尝试
            continue

        if guess < secret_number:
            print("📈 太小了！再大一点。")
        elif guess > secret_number:
            print("📉 太大了！再小一点。")
        else:
            print(f"\n🎉 恭喜你！你猜对了！数字就是 {secret_number}！")
            print(f"你一共用了 {attempts} 次就猜中了！")
            if attempts <= 3:
                print("🏆 太厉害了，你是天才！")
            elif attempts <= 5:
                print("👏 表现不错，继续加油！")
            else:
                print("💪 终于猜中了，运气也不错！")
            break
    else:
        print(f"\n😢 很遗憾，你已经用完所有机会了。")
        print(f"正确答案是：{secret_number}")

    print("\n感谢游玩，再见！👋")

if __name__ == "__main__":
    guess_number_game()
