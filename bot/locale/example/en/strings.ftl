help-text =
    <b>Left4Casino commands</b>

    /balance — show balance
    /bid [N] — set bet multiplier; values above balance become all-in
    /safe [±N] — show safe balance, deposit N points or withdraw N points
    /stats [@user] — player stats in the group
    /top — group leaderboard
    /give N @user — transfer points to a player
    /credit — request AI banker credit when balance is zero
    /dice N — start a PvP dice duel
    /take N @user — collect a debt from a debtor

    Slots: send Telegram dice with the 🎰 emoji in a group chat.

stop-text = Old keyboard removed. Current command list: /help

bar = BAR
grapes = grapes
lemon = lemon
seven = seven

spin-button-text = 🎰 Try it!

spin-fail = You lost the bet.
spin-success =
    You won {$score_change ->
         [one] {$score_change} point
        *[many] {$score_change} points
    }!

after-spin =
    Your combination: { $combo_text } (№{ $dice_value }).
    { $result_text } New score: <b>{ $new_score }</b>.

zero-balance =
    Your balance is zero. You can request AI banker credit with /credit. If an old keyboard remains, remove it with /stop.

# If you don't want to send sticker when balance is zero, disable feature in bot configuration
zero-balance-sticker = CAACAgIAAxkBAAEWXv5lAUAm76JOjvehtp18Gxb3if0eVQAC-hEAAknF8EuBzj23_M8x3jAE

menu-balance = Balance
menu-bid = Set bet
menu-safe = Safe balance
menu-stats = Player stats
menu-top = Leaderboard
menu-dice = Dice duel
menu-take = Collect debt
menu-give = Transfer points
menu-credit = Banker credit
menu-help = Command help
