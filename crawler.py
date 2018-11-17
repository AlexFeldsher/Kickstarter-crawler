""" Kickstarter crawler """
import json
import time
from collections import OrderedDict
from datetime import datetime
import logging
import requests
# import html2text
import argparse
from bs4 import BeautifulSoup


log = logging.getLogger(__name__)
handler = logging.StreamHandler()
log.addHandler(handler)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

PROJECTS = 'projects'
RECORDS = 'records'
RECORD = 'record'
REWARDS = 'rewards'
REWARD = 'reward'

CATEGORY_ID = 16    # technology
# SORT = 'magic'
# SORT = 'end_date'
SORT = 'popularity'
FORMAT = 'json'

LINK_SKELETON = 'https://www.kickstarter.com/discover/advanced?category_id={:d}&sort={}&page={:d}&format={}'


def discover_url_iter() -> str:
    """ Iterator for kickstarter discover pages """
    page = 0
    while True:
        link = LINK_SKELETON.format(CATEGORY_ID, SORT, page, FORMAT)
        page += 1
        log.debug('Discover link: %s', link)
        yield link


def get_digits(string: str) -> int:
    """ Returns only the digits from a given string """
    return int(''.join(filter(str.isdigit, string)))


def project_id(**kargs) -> int:
    """ Returns a unique id """
    project_id.id += 1
    log.debug('Got id: %d', project_id.id)
    return project_id.id
project_id.id = -1


def project_url(**kargs) -> str:
    """ Returns the project url """
    project = kargs['project']
    url = project['urls']['web']['project']
    url = url[:url.find('?ref')]
    # url = url[:url.find('?')] + '/description'
    log.debug('Got url: %s', url)
    return url


def project_creator(**kargs) -> str:
    """ Returns the project's creator name """
    project = kargs['project']
    creator = project['creator']['name']
    log.debug('Got creator: %s', creator)
    return creator


def project_title(**kargs) -> str:
    """ Returns the project's name """
    project = kargs['project']
    title = project['name']
    log.debug('Got title: %s', title)
    return title


def project_text(**kargs) -> str:
    """ Returns the project's page text """
    html = kargs['html']
    # clean_text = html2text.html2text(html)
    log.debug('Got text...')
    return html


def project_pledged(**kargs) -> float:
    """ Returns the dollars pledged to the project """
    project = kargs['project']
    pledged = project['converted_pledged_amount']
    log.debug('Got pledged dollars: %s', pledged)
    return float(pledged)


def project_backers(**kargs) -> str:
    """ Returns the number of backers """
    project = kargs['project']
    backers = project['backers_count']
    log.debug('Got number of backers: %s', backers)
    return backers


def project_days(**kargs) -> int:
    """ Returns the days left to reach goal """
    project = kargs['project']
    deadline = datetime.utcfromtimestamp(int(project['deadline']))
    time_left = deadline - datetime.now()
    log.debug('Got days left: %d', time_left.days)
    return time_left.days


def project_all_nothing(**kargs) -> bool:
    """
    Return true if project's kickstarter is all or nothing.
    otherwise, False.
    """
    html = kargs['html']
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.find('span', {'class': 'link-soft-black medium'})
    if text is None:
        log.debug('Got all or nothing: False')
        return False
    if 'All or nothing' in text.get_text():
        return True
    return False


def pledge_text(pledge) -> str:
    """ Returns the pledge text """
    text = pledge.find('div', {
        'class':
        'pledge__reward-description pledge__reward-description--expanded'
        })
    log.debug('Pledge text...')
    return text.get_text().strip()


def pledge_price(pledge) -> int:
    """ Returns the pledge price """
    money = pledge.find('span', {'class': 'pledge__currency-conversion'}).get_text().strip()
    money = get_digits(money)
    log.debug('Pledge money: %d', money)
    return money


def pledge_backers(pledge) -> int:
    """ Returns number of backers """
    backers_block = pledge.find('div', {'class': 'pledge__backer-stats'})
    backers = backers_block.find('span',
                                 {'class': 'pledge__backer-count'})
    # cleanup
    backers = backers.get_text().strip()
    backers = backers[:backers.find(' backer')]
    backers = backers.replace(',', '')  # remove ,
    log.debug('Pledge backers: %s', backers)
    return int(backers)


def pledge_total_backers(pledge) -> int:
    """
    Returns the pledge backers limit
    -1 = no limit
    -2 = limited but undefined
    """
    backers_block = pledge.find('div', {'class': 'pledge__backer-stats'})
    total_backers = backers_block.find('span', {'class': 'pledge__limit'})
    if total_backers is None:
        log.debug('Pledge total backers: %s', 'no limit')
        return -1
        # return 'no limit'
    text = total_backers.get_text().strip()
    if text == 'Reward no longer available':
        total = pledge_backers(pledge)
        log.debug('Pledge total backers: %d', total)
        return total
    # get last number from Limited (2 left of 2)
    try:
        total = int(text.split(' ')[-1][:-1])
    except ValueError:
        total = -2

    log.debug('Pledge total backers: %d', total)
    return total


field_func_map = OrderedDict([('id',             project_id),
                              ('url',            project_url),
                              ('Creator',        project_creator),
                              ('Title',          project_title),
                              ('Text',           project_text),
                              ('DollarsPledged', project_pledged),
                              ('NumBackers',     project_backers),
                              ('DaysToGo',       project_days),
                              ('AllOrNothing',   project_all_nothing)])

reward_func_map = OrderedDict([('Text',                 pledge_text),
                               ('Price',                pledge_price),
                               ('NumBackers',           pledge_backers),
                               ('TotalPossibleBackers', pledge_total_backers)])


def crawl_project(project: dict) -> OrderedDict:
    """ Crawls a given project and returns a record dictionary """
    project_dict: OrderedDict = OrderedDict()
    project_html: str = requests.get(project_url(project=project)).text

    # parse discover page json
    for key, func in field_func_map.items():
        project_dict[key] = func(project=project,
                                 html=project_html)

    # parse project page
    project_dict[REWARDS] = OrderedDict()
    project_dict[REWARDS][REWARD] = list()
    soup = BeautifulSoup(project_html, 'html.parser')
    pledges = soup.findAll('div', {'class': 'pledge__info'})
    for i, pledge_info in enumerate(pledges[1:]):  # ignore the first pledge without reward
        project_dict[REWARDS][REWARD].append(OrderedDict())
        reward_dict = project_dict[REWARDS][REWARD][i]

        for key, func in reward_func_map.items():
            reward_dict[key] = func(pledge_info)

    return project_dict


def crawl(num_projects: int) -> dict:
    """
    Crawls kickstarter and returns a json representation of the technology
    projects found in kickstarter
    """
    crawled_urls: set = set()
    data_dict: OrderedDict = OrderedDict()
    data_dict[RECORDS] = OrderedDict()
    data_dict[RECORDS][RECORD] = list()

    for discover_url in discover_url_iter():
        response = requests.get(discover_url)
        data = json.loads(response.text)
        log.debug('Json url: %s', response.url)

        for project in data[PROJECTS]:
            # check if already crawled project
            url = project_url(project=project)
            if url in crawled_urls:
                continue
            crawled_urls.add(url)
            log.info('%d/%d Crawling %s', len(crawled_urls), num_projects, url)

            project_dict = crawl_project(project)
            data_dict[RECORDS][RECORD].append(project_dict)
            time.sleep(2)

            if len(crawled_urls) == num_projects:
                break
        if len(crawled_urls) == num_projects:
            break
        time.sleep(2)
    return data_dict


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Kickstarter technology projects crawler')
    parser.add_argument('-n', '--num_projects', type=int, nargs=1, help='number of projects to crawl')
    parser.add_argument('-o', '--output', type=str, nargs=1, help='output file path')
    parser.add_argument('--debug', action='store_true', help='enable logging')
    args = parser.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    _data: dict = crawl(args.num_projects[0])
    with open(args.output[0], 'w', encoding='utf8') as f:
        json.dump(_data, f, ensure_ascii=False, indent=4)
        # f.write(_data)
