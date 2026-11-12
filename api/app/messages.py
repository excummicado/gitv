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
    "Only event organizers and admins can fill in results.": "Заполнять результаты могут только организаторы и админы.",
    "Only a super admin can do this.": "Это может сделать только супер-админ.",
    "Sign-up expired. Start again with Discord.": "Время регистрации истекло. Начните заново через Discord.",
    "This Discord account already has a GITV profile. Sign in instead.": "У этого Discord-аккаунта уже есть профиль GITV. Просто войдите.",
    "This nickname is taken.": "Этот ник занят.",
    # Results filled in by hand
    "Give each player's times once.": "Укажите время каждого игрока один раз.",
    "No such player in this game.": "В этой игре нет такого игрока.",
    "Each room's time must be between 0 and 300 seconds.": "Время комнаты должно быть от 0 до 300 секунд.",
    "Restarts must be between 0 and 99.": "Рестартов может быть от 0 до 99.",
    "No such game in this match.": "В этом матче нет такой игры.",
    "This game has no times filled in by hand.": "В этой игре нет времени, заполненного вручную.",
    "A technical defeat can only be given in a game of two players.": "Тех. поражение можно назначить только в игре двух игроков.",
    "This game has no technical defeat given by hand.": "В этой игре нет тех. поражения, назначенного вручную.",
    "This match isn't on the draft site.": "Этого матча нет на сайте драфтов.",
    "The draft site didn't answer. Try again later.": "Сайт драфтов не ответил. Попробуйте позже.",
    "You can only fill in results of your own tournaments.": "Заполнять результаты можно только в турнирах своих организаторов.",
    "You can only schedule matches of your own tournaments.": "Расписывать можно только матчи турниров своих организаторов.",
    "No such side in this match.": "В этом матче нет такой стороны.",
    "This player has no page on the site, so they can't be set as the winner.": "У этого игрока нет страницы на сайте, поэтому его нельзя сделать победителем.",
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
    "You can't change your own organizers.": "Своих организаторов менять нельзя.",
    "Only a super admin can change an admin's organizers.": "Менять организаторов админа может только супер-админ.",
    "No organizer with this id.": "Организатора с таким id нет.",
    "This member doesn't run this organizer.": "Этот участник не ведёт турниры этого организатора.",
    # Matches and players
    "No such match.": "Такого матча нет.",
    "No such tournament.": "Такого турнира нет.",
    "No such player.": "Такого игрока нет.",
    "No games in major tournaments.": "Нет игр в мейджор-турнирах.",
    "No games in tournaments since that date.": "Нет игр в турнирах с этой даты.",
    "No games in tournaments between those dates.": "Нет игр в турнирах за эти даты.",
    "This player didn't play that tournament.": "Игрок не участвовал в этом турнире.",
    "No roster for this player in that tournament.": "Нет ростера игрока на этом турнире.",
    # Matches of the day
    "The time needs a time zone.": "Время должно быть с часовым поясом.",
    "Pick two different players.": "Выберите двух разных игроков.",
    "No such scheduled match.": "Такого матча дня нет.",
    "Only its author or an admin can remove it.": "Удалить может только автор или админ.",
    "Only its author or an admin can edit it.": "Изменить может только автор или админ.",
    # Articles and news
    "No such article.": "Такой статьи нет.",
    "No such news.": "Такой новости нет.",
    "Write the news first.": "Сначала напишите новость.",
    "Only its author or an admin can change it.": "Изменить может только автор или админ.",
    "The article is empty.": "Статья пустая.",
    "The document is empty.": "Документ пустой.",
    "It has no translation.": "У статьи нет перевода.",
    "The document must be 20 MB or smaller.": "Документ должен быть не больше 20 МБ.",
    "That isn't a Word document (.docx).": "Это не документ Word (.docx).",
    "Couldn't read the document.": "Не удалось прочитать документ.",
    "The document unpacks to too much. Make it smaller, or with smaller pictures.": "Документ слишком большой в распакованном виде. Уменьшите его или картинки в нём.",
}

# Messages with numbers or dates in them.
RU_PATTERNS = [
    (re.compile(r"Too many requests\. Try again in (\d+) min\."), r"Слишком много запросов. Попробуйте через \1 мин."),
    (re.compile(r"Ask for at most (\d+) days\."), r"Можно запросить не больше \1 дн."),
    (re.compile(r"Pick a time from today up to (\d+) days ahead\."), r"Выберите время от сегодня и до \1 дн. вперёд."),
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
