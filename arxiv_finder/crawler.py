"""
论文爬取模块 — 提供 arXiv 网页爬虫和 arXiv API 两种搜索方式。
"""

import datetime
import os
import re
from typing import List, Tuple

import requests
import tenacity
from bs4 import BeautifulSoup

from core.paper import Paper
from core.utils import validate_title


# =============================================================================
# arXiv 网页爬虫（来自 chat_arxiv.py 的 Reader 爬取逻辑）
# =============================================================================

class ArxivWebCrawler:
    """
    通过 arXiv 网站搜索并下载论文 PDF。

    Parameters
    ----------
    root_path : str
        PDF 文件存储根目录。
    """

    def __init__(self, root_path: str = './'):
        self.root_path = root_path

    def search(self, query: str, page_num: int = 1, days: int = 2,
               max_results: int = 5) -> List[Paper]:
        """
        搜索 arXiv 网站并下载匹配的论文。

        Parameters
        ----------
        query : str
            搜索关键词。
        page_num : int
            搜索页数（每页 ~50 篇）。
        days : int
            只获取最近 N 天内发布的论文。
        max_results : int
            最多返回的论文数量。

        Returns
        -------
        list[Paper]
        """
        titles, links, dates, abstracts, authors = self._get_all_titles_from_web(query, page_num, days)
        paper_list = []
        for title_index, title in enumerate(titles):
            if title_index + 1 > max_results:
                break
            print(title_index, title, links[title_index], dates[title_index])
            url = links[title_index] + ".pdf"
            filename = self._try_download_pdf(url, title, query)
            paper = Paper(
                path=filename, 
                url=links[title_index], 
                title=title,
                abs=abstracts[title_index],
                authers=authors[title_index]
            )
            paper.parse_pdf()
            paper_list.append(paper)
        return paper_list

    # -----------------------------------------------------------------
    # URL 构建
    # -----------------------------------------------------------------

    @staticmethod
    def _get_url(keyword: str, page: int) -> str:
        """生成 arXiv 搜索页面 URL。"""
        base_url = "https://arxiv.org/search/?"
        params = {
            "query": keyword,
            "searchtype": "all",
            "abstracts": "show",
            "order": "-announced_date_first",
            "size": 50,
        }
        if page > 0:
            params["start"] = page * 50
        return base_url + requests.compat.urlencode(params)

    # -----------------------------------------------------------------
    # 页面解析
    # -----------------------------------------------------------------

    @staticmethod
    def _get_titles(url: str, days: int = 1) -> Tuple[list, list, list, list, list]:
        """从 arXiv 搜索结果页解析论文标题、链接、日期、摘要和作者。"""
        titles, links, dates, abstracts, authors_list = [], [], [], [], []
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("li", class_="arxiv-result")
        today = datetime.date.today()
        last_days = datetime.timedelta(days=days)

        for article in articles:
            try:
                title = article.find("p", class_="title").text.strip()
                link = article.find("span").find_all("a")[0].get('href')
                date_text = article.find("p", class_="is-size-7").text
                date_text = date_text.split('\n')[0].split("Submitted ")[-1].split("; ")[0]
                date_text = datetime.datetime.strptime(date_text, "%d %B, %Y").date()
                
                # 提取摘要
                abstract_p = article.find("span", class_="abstract-full")
                abs_text = ""
                if abstract_p:
                    # 去除 "△ Less" 文本
                    span_less = abstract_p.find("span", text="△ Less")
                    if span_less:
                        span_less.decompose()
                    abs_text = abstract_p.text.strip()
                
                # 提取作者
                authors_p = article.find("p", class_="authors")
                authors = []
                if authors_p:
                    for a in authors_p.find_all("a"):
                        authors.append(a.text.strip())

                if today - date_text <= last_days:
                    titles.append(title)
                    links.append(link)
                    dates.append(date_text)
                    abstracts.append(abs_text)
                    authors_list.append(authors)
            except Exception as e:
                print("error:", e)

        return titles, links, dates, abstracts, authors_list

    def _get_all_titles_from_web(self, keyword: str, page_num: int = 1,
                                 days: int = 1) -> Tuple[list, list, list, list, list]:
        """翻页获取所有论文信息。"""
        title_list, link_list, date_list, abstract_list, author_list = [], [], [], [], []
        for page in range(page_num):
            url = self._get_url(keyword, page)
            titles, links, dates, abstracts, authors = self._get_titles(url, days)
            if not titles:
                break
            for i, title in enumerate(titles):
                print(page, i, title, links[i], dates[i])
            title_list.extend(titles)
            link_list.extend(links)
            date_list.extend(dates)
            abstract_list.extend(abstracts)
            author_list.extend(authors)
        print("-" * 40)
        return title_list, link_list, date_list, abstract_list, author_list

    # -----------------------------------------------------------------
    # 下载
    # -----------------------------------------------------------------

    def _download_pdf(self, url: str, title: str, query: str) -> str:
        """下载单篇论文 PDF。"""
        response = requests.get(url)
        date_str = str(datetime.datetime.now())[:13].replace(' ', '-')
        path = os.path.join(self.root_path, 'pdf_files', validate_title(query) + '-' + date_str)
        os.makedirs(path, exist_ok=True)
        filename = os.path.join(path, validate_title(title)[:80] + '.pdf')
        with open(filename, "wb") as f:
            f.write(response.content)
        return filename

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
                    stop=tenacity.stop_after_attempt(5),
                    reraise=True)
    def _try_download_pdf(self, url: str, title: str, query: str) -> str:
        return self._download_pdf(url, title, query)


# =============================================================================
# arXiv API 爬虫（来自 chat_paper.py 的 Reader 爬取逻辑）
# =============================================================================

class ArxivAPICrawler:
    """
    通过 arXiv Python API 搜索并下载论文 PDF。

    Parameters
    ----------
    root_path : str
        PDF 文件存储根目录。
    """

    def __init__(self, root_path: str = './'):
        self.root_path = root_path

    def search(self, query: str, key_word: str = '',
               sort=None, max_results: int = 30,
               filter_keys: str = '') -> List[Paper]:
        """
        通过 arXiv API 搜索论文，按关键词过滤，下载 PDF 并解析。

        Parameters
        ----------
        query : str
            arXiv 查询字符串。
        key_word : str
            研究领域关键词。
        sort : arxiv.SortCriterion, optional
            排序方式。
        max_results : int
            最大搜索结果数。
        filter_keys : str
            空格分隔的过滤关键词，要求每个词都出现在摘要中。

        Returns
        -------
        list[Paper]
        """
        import arxiv

        if sort is None:
            sort = arxiv.SortCriterion.SubmittedDate

        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=sort,
            sort_order=arxiv.SortOrder.Descending,
        )

        # 过滤
        filter_results = []
        print("all search:")
        for index, result in enumerate(search.results()):
            print(index, result.title, result.updated)

        for index, result in enumerate(search.results()):
            if not filter_keys:
                filter_results.append(result)
                continue
            abs_text = result.summary.replace('-\n', '-').replace('\n', ' ')
            meet_num = 0
            for f_key in filter_keys.split(" "):
                if f_key.lower() in abs_text.lower():
                    meet_num += 1
            if meet_num == len(filter_keys.split(" ")):
                filter_results.append(result)

        print(f"筛选后剩下的论文数量: {len(filter_results)}")
        for index, result in enumerate(filter_results):
            print(index, result.title, result.updated)

        return self._download_papers(filter_results, query, key_word)

    def _download_papers(self, filter_results, query: str, key_word: str) -> List[Paper]:
        """下载过滤后的论文列表。"""
        import datetime

        date_str = str(datetime.datetime.now())[:13].replace(' ', '-')
        path = os.path.join(
            self.root_path, 'pdf_files',
            query.replace('au: ', '').replace('title: ', '').replace('ti: ', '').replace(':', ' ')[:25]
            + '-' + date_str
        )
        os.makedirs(path, exist_ok=True)

        print("All_paper:", len(filter_results))
        paper_list = []
        for r_index, result in enumerate(filter_results):
            try:
                title_str = validate_title(result.title)
                pdf_name = title_str + '.pdf'
                self._try_download_pdf(result, path, pdf_name)
                paper_path = os.path.join(path, pdf_name)
                print("paper_path:", paper_path)
                paper = Paper(
                    path=paper_path,
                    url=result.entry_id,
                    title=result.title,
                    abs=result.summary.replace('-\n', '-').replace('\n', ' '),
                    authers=[str(aut) for aut in result.authors],
                )
                paper.parse_pdf()
                paper_list.append(paper)
            except Exception as e:
                print("download_error:", e)
        return paper_list

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
                    stop=tenacity.stop_after_attempt(5),
                    reraise=True)
    def _try_download_pdf(self, result, path: str, pdf_name: str):
        result.download_pdf(path, filename=pdf_name)
