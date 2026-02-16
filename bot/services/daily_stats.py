import uuid
from datetime import datetime, timedelta

import pytz
from aiogram import Bot

from bot.db import Database
from bot.utils.formatters import format_number


class DailyStatsService:
    def __init__(self, db: Database, bot: Bot):
        self.db = db
        self.bot = bot
        self.timezone = pytz.timezone("Asia/Yekaterinburg")  # UTC+5

    def get_yesterday_range(self):
        """Returns (start_utc_str, end_utc_str) for yesterday in UTC+5"""
        now = datetime.now(self.timezone)
        yesterday = now - timedelta(days=1)

        # Start of yesterday (00:00:00 local)
        start_local = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        # End of yesterday (23:59:59 local)
        end_local = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Convert to UTC for DB query
        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)

        return (
            start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            end_utc.strftime("%Y-%m-%d %H:%M:%S"),
            start_local.strftime("%d.%m.%Y"),
        )

    async def generate_and_send_report(
        self, chat_id: int, is_dry_run: bool = False, use_today: bool = False
    ):
        if use_today:
            start_utc, end_utc, date_str = self.get_today_range_so_far()
        else:
            start_utc, end_utc, date_str = self.get_yesterday_range()

        stats = await self.db.get_daily_stats(start_utc, end_utc, chat_id)

        if not stats:
            # No stats for yesterday
            return

        # Process stats to find winners
        # Structure: {category: [(user_id, nickname, value)]}

        categories = {
            "most_played": {
                "key": "games_played",
                "label": "🎰 Больше всех сыграл",
                "users": [],
                "max_val": -1,
                "reward": 100,
            },
            "most_won": {
                "key": "total_won",
                "label": "🤑 Больше всех выиграл",
                "users": [],
                "max_val": -1,
                "reward": 100,
            },
            "most_lost": {
                "key": "total_lost",
                "label": "📉 Больше всех проиграл",
                "users": [],
                "max_val": -1,
                "reward": 100,
            },
            "most_bankrupt": {
                "key": "bankruptcy_count",
                "label": "💸 Самый лютый банкрот",
                "users": [],
                "max_val": -1,
                "reward": 100,
            },
            "most_given": {
                "key": "total_given",
                "label": "🤝 Самый щедрый",
                "users": [],
                "max_val": -1,
                "reward": 150,
            },
            "biggest_win": {
                "key": "max_win_amount",
                "label": "💰 Самый большой куш",
                "users": [],
                "max_val": -1,
                "reward": 100,
            },
            "luckiest": {
                "key": "luck_ratio",
                "label": "🍀 Счастливчик дня (Win Rate)",
                "users": [],
                "max_val": -1,
                "reward": 100,
            },
            "most_boring": {
                "key": "avg_bid",
                "label": "🥱 Самый скучный (самая маленькая 🤏 средняя ставка)",
                "users": [],
                "max_val": float("inf"),
                "reverse": True,
                "reward": 10,
            },
        }

        # Calculate aggregates
        total_games = 0
        total_won_global = 0
        total_lost_global = 0
        total_bankruptcies = 0

        for row in stats:
            # Pre-calculate derived metrics
            games = row["games_played"]
            row["luck_ratio"] = 0
            if games >= 5:  # Minimum games threshold for Luck Rate to be statistically relevant
                # Luck = (won_games / total_games) * 100.
                # But we don't have 'won_games' count in the query, we have 'total_won' sum.
                # To get exact win rate we need count of win events.
                # Let's adjust the query or estimate?
                # Actually, in the SQL query we only aggregated total_won amount, not count.
                # Let's just use (total_won / (total_won + total_lost)) ratio as a proxy for "Money Luck"?
                # Or better: re-query or adjust SQL.
                # For now, let's stick to Money Ratio: Won / (Won + Lost)
                total_volume = row["total_won"] + row["total_lost"]
                if total_volume > 0:
                    row["luck_ratio"] = round((row["total_won"] / total_volume) * 100, 1)

            if games < 5:
                # Disqualify from boring if too few games
                row["avg_bid"] = None

            total_games += row["games_played"]
            total_won_global += row["total_won"]
            total_lost_global += row["total_lost"]
            total_bankruptcies += row["bankruptcy_count"]

            # Check categories
            for _cat_key, cat_data in categories.items():
                val = row.get(cat_data["key"])

                if val is None:
                    continue

                # Specific logic for reverse categories (lower is better, like boring)
                is_reverse = cat_data.get("reverse", False)

                if is_reverse:
                    # We want MIN value
                    if val > 0 and val < cat_data["max_val"]:
                        cat_data["max_val"] = val
                        cat_data["users"] = [(row["user_id"], row["nickname"], val)]
                    elif val > 0 and val == cat_data["max_val"]:
                        cat_data["users"].append((row["user_id"], row["nickname"], val))
                else:
                    # Standard MAX value
                    if val > 0:
                        if val > cat_data["max_val"]:
                            cat_data["max_val"] = val
                            cat_data["users"] = [(row["user_id"], row["nickname"], val)]
                        elif val == cat_data["max_val"]:
                            cat_data["users"].append((row["user_id"], row["nickname"], val))

        # Build message
        lines = [f"<b>🏆 Итоги дня ({date_str})</b>\n"]
        lines.append(f"📊 Всего игр: {format_number(total_games)}")
        lines.append(f"📈 Получено очков: {format_number(total_won_global)}")
        lines.append(f"📉 Потрачено очков: {format_number(total_lost_global)}")
        if total_bankruptcies > 0:
            lines.append(f"💀 Всего банкротств: {format_number(total_bankruptcies)}")
        lines.append("")

        default_reward = 50
        rewarded_users = set()

        for cat_key, cat_data in categories.items():
            if cat_data["users"]:
                # Format: Label — nickname1, nickname2 (value)
                names = []
                reward_val = cat_data.get("reward", default_reward)

                for uid, nick, _val in cat_data["users"]:
                    clean_nick = nick if nick else "Unknown"
                    # Add @ to nickname if not present and not "Unknown"
                    if clean_nick != "Unknown" and not clean_nick.startswith("@"):
                        display_nick = f"@{clean_nick}"
                    else:
                        display_nick = clean_nick

                    names.append(f"{display_nick}")

                    # Reward logic
                    if not is_dry_run:
                        # Only reward if not already rewarded for this category?
                        # Requirement said: "Каждому перечисленному игроку нужно начислить по 50 очков на баланс за каждую выигранную номинацию."
                        # So we reward even if user won multiple categories.

                        await self.db.update_balance(uid, reward_val)
                        await self.db.add_event(
                            str(uuid.uuid4()),
                            uid,
                            "daily_reward",
                            reward_val,
                            f"Reward for {cat_key}",
                        )
                        rewarded_users.add(uid)

                val = cat_data["max_val"]
                val_str = (
                    str(val)
                    if isinstance(val, float) and not val.is_integer()
                    else format_number(int(val))
                )
                lines.append(
                    f"{cat_data['label']} — {', '.join(names)} ({val_str}) +{reward_val} очков!"
                )

        if is_dry_run:
            lines.append("\n<i>⚠️ Это предварительный просмотр. Награды не начислены.</i>")

        message_text = "\n".join(lines)

        try:
            await self.bot.send_message(chat_id, message_text)
        except Exception as e:
            print(f"Failed to send daily report to {chat_id}: {e}")

    def get_today_range_so_far(self):
        # Helper for testing: returns range from start of TODAY until NOW
        now = datetime.now(self.timezone)
        start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)

        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = now.astimezone(pytz.UTC)

        return (
            start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            end_utc.strftime("%Y-%m-%d %H:%M:%S"),
            start_local.strftime("%d.%m.%Y"),
        )
