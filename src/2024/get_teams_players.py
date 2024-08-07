import asyncio
import json
import re

from playwright.async_api import async_playwright, Playwright


async def set_up(playwright: Playwright, headless):
    chromium = playwright.chromium
    browser = await chromium.launch(headless=headless)
    page = await browser.new_page()
    return browser, page


async def tear_down(browser):
    await browser.close()


async def get_national_teams(page, link):
    await page.goto(link, timeout=10000)

    national_team_class = 'tableCellParticipant__name'
    national_teams = await page.locator(f'.{national_team_class}').all()
    national_teams_data = {await team.inner_text(): await team.get_attribute('href') for team in national_teams}
    return national_teams_data


async def get_teams_players(page, link):
    await page.goto(link, timeout=10000)
    player_row_class = 'lineupTable__row'
    player_name_class = 'lineupTable__cell--name'
    player_age_class = 'lineupTable__cell--age'
    player_flag_class = 'lineupTable__cell--flag'
    player_goal_class = 'lineupTable__cell--goal'
    player_assist_class = 'lineupTable__cell--assist'

    players = await page.locator(f'.{player_row_class}').all()
    players_data = {}

    for player_row in players:
        player = player_row.locator(f'.{player_name_class}')
        name = (await player.inner_text()).strip()
        name_parts = name.rsplit(' ', 1)
        surname, first_name = name_parts if len(name_parts) == 2 else (name_parts[0], '')
        age = await player_row.locator(f'.{player_age_class}').inner_text()
        short_name = f'{surname} {first_name[0]}.' if first_name else surname
        link = await player.get_attribute('href')
        club = await player_row.locator(f'.{player_flag_class}').first.get_attribute('title')
        try:
            goals = await player_row.locator(f'.{player_goal_class}').inner_text()
            assists = await player_row.locator(f'.{player_assist_class}').inner_text()
        except:
            goals, assists = 0, 0
        players_data[name] = {'short_name': short_name, 'age': age, 'club_ref': club, 'goals': int(goals),
                              'assists': int(assists), 'link': link}
    await complete_team_players_data(page, players_data)
    return players_data


async def get_extra_player_data(page, player_link):
    link = f'https://www.flashscore.com{player_link}'
    await page.goto(link, timeout=10000)

    role_class = 'playerTeam'
    league_country_class = 'careerTab__competition'
    club_href_class = 'careerTab__competitionHref'

    role, value, club, league, league_country = '', '', '', '', ''

    try:
        role = await (page.locator(f'.{role_class}')).inner_text()
        role = role.split(' ', 1)[0]
        if role.lower() == 'coach' or role == '':
            return role, '', '', '', ''
        value = page.get_by_text(re.compile(r'[$€]\w+')).first
        value = await value.inner_text()
        club = await (page.locator(f'.{club_href_class}').nth(0)).get_attribute('title')
        competition = page.locator(f'.{league_country_class}').nth(1)
        league_country = await (competition.locator('span')).get_attribute('title')
        league = await (competition.locator('a')).get_attribute('title')
    except Exception:
        print('***EXCEPTION***', player_link)
    return role, value, club, league, league_country


async def complete_team_players_data(page, team_players_dict):
    for player, player_data in team_players_dict.items():
        role, value, club, league, league_country = await get_extra_player_data(page, player_data['link'])
        team_players_dict[player]['role'] = role
        team_players_dict[player]['value'] = value
        team_players_dict[player]['club'] = club
        team_players_dict[player]['league'] = f'{league} ({league_country})'
        team_players_dict[player]['league_country'] = league_country


def retrieve_coaches(json_file, json_players, json_coaches):
    json_data = read_json(json_file)
    coaches = {}
    for country, players in json_data.items():
        for player, dd in players.items():
            role = dd['role']
            if role == 'Coach':
                dd['name'] = player
                dd.pop('role')
                dd.pop('value')
                dd.pop('club')
                dd.pop('club_ref')
                dd.pop('league')
                dd.pop('league_country')
                dd.pop('goals')
                dd.pop('assists')
                coaches[country] = dd

    for country, coach_dict in coaches.items():
        json_data[country].pop(coach_dict['name'])

    save_data(json_data, json_players)
    save_data(coaches, json_coaches)


def flatten_players_hierarchy(json_file, js_file_name='players.js'):
    json_data = read_json(json_file)
    all_players = []
    for country, players in json_data.items():
        for player, dd in players.items():
            dd['national_team'] = country
            dd['name'] = player
            all_players.append(dd)

    with open(js_file_name, 'w', encoding='utf-8') as f:
        f.write('const players = ')
        json.dump(all_players, f, ensure_ascii=False, indent=4)


def read_json(json_file):
    with open(json_file, 'r', encoding='utf-8') as f:
        d = json.load(f)
    return d


def save_data(data, file_name='data.json'):
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


async def main(link, data_json, players_json, coaches_json, players_js):
    async with async_playwright() as playwright:
        browser, page = await set_up(playwright, headless)
        national_teams = await get_national_teams(page, link)
        teams_data = {}

        for team, code in national_teams.items():
            if team in teams_data:
                continue
            team_players_link = f'https://www.flashscore.com{code}squad/'
            team_players = await get_teams_players(page, team_players_link)
            teams_data[team] = team_players

        save_data(teams_data, data_json)
        await tear_down(browser)

    retrieve_coaches(data_json, players_json, coaches_json)
    flatten_players_hierarchy(players_json, players_js)


def analyse_clubs(json_file='data.json'):
    with open(json_file, 'r', encoding='utf-8') as f:
        d = json.load(f)
    cnt = 0
    for country, players in d.items():
        for player, players_dict in players.items():
            if players_dict['role'] != 'Coach' and players_dict['club'] != players_dict['club_ref']:
                cnt += 1
                print(f'{cnt}. {country} - {player} - {players_dict["link"]}'
                      f'\n\t{players_dict["club"]} - {players_dict["club_ref"]}')


if __name__ == '__main__':
    headless = True
    euro_link = 'https://www.flashscore.com/football/europe/euro/standings/#/EcpQtcVi/table'
    copa_link = 'https://www.flashscore.com/football/south-america/copa-america/standings/#/zDzsPsN5/live'
    data_json_file = 'data.json'
    players_json_file = 'players.json'
    coaches_json_file = 'coaches.json'
    players_js_file = '../../js/2024/players.js'
    copa_files = [f'{pref}_copa.{ext}' for pref, ext in [name.rsplit('.', 1) for name in (
        data_json_file, players_json_file, coaches_json_file, players_js_file)]]

    asyncio.run(main(euro_link, data_json_file, players_json_file, coaches_json_file, players_js_file))
    asyncio.run(main(copa_link, *copa_files))
    analyse_clubs(data_json_file)
