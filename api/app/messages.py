"""API error messages in the visitor's language.

Errors are raised in English; when the site is in Russian (the gitv-lang cookie the site sets, or an
Accept-Language that starts with ru) the exception handler in main.py swaps the message for its Russian
version here. A message missing from the table goes out in English.
"""

import re

from fastapi import Request

RU = {
    # Sign-in and accounts
    "Could not validate credentials": "Не удалось проверить вход. Войдите снова.",
    "This account is banned.": "Этот аккаунт заблокирован.",
    "Only an admin can do this.": "Это может сделать только админ.",
    "Only event organizers and admins can edit players.": "Редактировать игроков могут только организаторы и админы.",
    "Only a super admin can do this.": "Это может сделать только супер-админ.",
    "Sign-up expired. Start again with Discord.": "Время регистрации истекло. Начните заново через Discord.",
    "This Discord account already has a GITV profile. Sign in instead.": "У этого Discord-аккаунта уже есть профиль GITV. Просто войдите.",
    "This nickname is taken.": "Этот ник занят.",
    "Another GITV account already uses this Discord email.": "Почта этого Discord уже используется другим аккаунтом GITV.",
    # Admin
    "No member with this nickname.": "Участника с таким ником нет.",
    "You can't change your own role.": "Свою роль менять нельзя.",
    "This member is a super admin.": "Этот участник — супер-админ.",
    "Only a super admin can make someone an admin.": "Назначать админов может только супер-админ.",
    "Only a super admin can change an admin's role.": "Менять роль админа может только супер-админ.",
    "This member already has that role.": "У участника уже эта роль.",
    "You can't ban yourself.": "Себя заблокировать нельзя.",
    "A super admin can't be banned.": "Супер-админа заблокировать нельзя.",
    "Only a super admin can ban an admin.": "Заблокировать админа может только супер-админ.",
    "This member is already banned.": "Участник уже заблокирован.",
    "This member isn't banned.": "Участник не заблокирован.",
    # Matches and players
    "No such match.": "Такого матча нет.",
    "No such tournament.": "Такого турнира нет.",
    "No such player.": "Такого игрока нет.",
    "No games in major tournaments.": "Нет игр в мейджор-турнирах.",
    "No games in tournaments since that date.": "Нет игр в турнирах с этой даты.",
    "This player didn't play that tournament.": "Игрок не участвовал в этом турнире.",
    "No roster for this player in that tournament.": "Нет ростера игрока на этом турнире.",
    # Matches of the day
    "The time needs a time zone.": "Время должно быть с часовым поясом.",
    "Pick two different players.": "Выберите двух разных игроков.",
    "No such scheduled match.": "Такого матча дня нет.",
    "Only its author or an admin can remove it.": "Удалить может только автор или админ.",
    # Suggestions and profiles
    "Send a name or a birthday.": "Укажите имя или день рождения.",
    "You can edit players directly instead of suggesting.": "Вы можете редактировать игроков напрямую, без предложений.",
    "You can't make suggestions.": "Вам нельзя отправлять предложения.",
    "Suggest a name or a birthday.": "Предложите имя или день рождения.",
    "You already have a suggestion for this player waiting for review.": "У вас уже есть предложение по этому игроку на проверке.",
    "No such suggestion.": "Такого предложения нет.",
    "Admins review suggestions; there's nothing to stop.": "Админы сами проверяют предложения — запрещать нечего.",
    "This member already can't suggest.": "Этому участнику уже запрещены предложения.",
    "This member can already suggest.": "Этому участнику уже разрешены предложения.",
}

# Messages with numbers or dates in them.
RU_PATTERNS = [
    (re.compile(r"Too many requests\. Try again in (\d+) min\."), r"Слишком много запросов. Попробуйте через \1 мин."),
    (re.compile(r"Ask for at most (\d+) days\."), r"Можно запросить не больше \1 дн."),
    (re.compile(r"Pick a time from today up to (\d+) days ahead\."), r"Выберите время от сегодня и до \1 дн. вперёд."),
    (
        re.compile(r"A name is letters, spaces, hyphens, apostrophes or dots, up to (\d+) characters\."),
        r"Имя — буквы, пробелы, дефисы, апострофы или точки, до \1 символов.",
    ),
    (re.compile(r"The birthday must be between (\S+) and (\S+)\."), r"День рождения должен быть между \1 и \2."),
    (
        re.compile(r"You have (\d+) suggestions waiting for review; wait until they're checked\."),
        r"У вас на проверке предложений: \1. Дождитесь, пока их проверят.",
    ),
    (re.compile(r"This suggestion was already accepted\."), "Это предложение уже принято."),
    (re.compile(r"This suggestion was already rejected\."), "Это предложение уже отклонено."),
]


def request_lang(request: Request) -> str:
    lang = request.cookies.get("gitv-lang")
    if lang in ("en", "ru"):
        return lang
    return "ru" if request.headers.get("accept-language", "").lower().startswith("ru") else "en"


def translate(message: str, lang: str) -> str:
    if lang != "ru":
        return message
    if message in RU:
        return RU[message]
    for pattern, replacement in RU_PATTERNS:
        if pattern.fullmatch(message):
            return pattern.sub(replacement, message)
    return message
