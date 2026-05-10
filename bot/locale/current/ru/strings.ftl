help-text =
    <b>Команды Left4Casino</b>

    /balance — показать баланс
    /bid [N] — установить множитель ставки; если N больше баланса, ставка станет all-in
    /safe [±N] — показать сейф, положить N очков или снять N очков
    /stats [@user] — статистика игрока в группе
    /top — топ игроков группы
    /give N @user — перевести очки игроку
    /credit — запросить кредит у ИИ-банкира при нулевом балансе
    /dice N — вызвать игрока на PvP-дуэль на кубиках
    /take N @user — взыскать долг с должника

    Слоты: отправьте Telegram dice с emoji 🎰 в групповом чате.

stop-text = Старая клавиатура удалена. Список актуальных команд: /help

bar = BAR
grapes = виноград
lemon = лимон
seven = семь

spin-button-text = 🎰 Испытать удачу!

score-points = {$score-value ->
    [one] {$score-value} очко
    [few] {$score-value} очка
   *[many] {$score-value} очков
}

spin-fail =
    К сожалению, вы не выиграли.

spin-success =
    <b>Вы выиграли {score-points}!</b>

after-spin =
    Ваша комбинация: {$combo_text} (№{$dice_value}).
    {$result_text}
    У вас осталось {score-points}.

zero-balance =
    Ваш баланс равен нулю. Можно запросить кредит у ИИ-банкира командой /credit. Если осталась старая клавиатура, уберите её командой /stop.

# Если не хотите использовать стикер, укажите это в конфиге
zero-balance-sticker = CAACAgIAAxkBAAEFGxpfqmqG-MltYIj4zjmFl1eCBfvhZwACuwIAAuPwEwwS3zJY4LIw9B4E

menu-balance = Баланс
menu-bid = Установить ставку
menu-safe = Сейф
menu-stats = Статистика игрока
menu-top = Топ игроков
menu-dice = Дуэль на кубиках
menu-take = Взыскать долг
menu-give = Перевести очки
menu-credit = Кредит у банкира
menu-help = Справка по командам
