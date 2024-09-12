import os
import random
import time
import notion_client

import html2text
from markdownify import markdownify

from flomo.flomo_api import FlomoApi
from notionify import notion_utils
from notionify.md2notion import Md2NotionUploader
from notionify.notion_cover_list import cover
from notionify.notion_helper import NotionHelper
from utils import truncate_string, is_within_n_days

class Flomo2Notion:
    def __init__(self):
        self.flomo_api = FlomoApi()
        self.notion_helper = NotionHelper()
        self.uploader = Md2NotionUploader()

    @staticmethod
    def clean_and_truncate_tag(tag):
        return tag.replace(',', '')[:100]

    def insert_memo(self, memo):
        print("insert_memo:", memo)
        content_md = markdownify(memo['content'])
        parent = {"database_id": self.notion_helper.page_id, "type": "database_id"}
        content_text = html2text.html2text(memo['content'])
        
        cleaned_tags = [self.clean_and_truncate_tag(tag) for tag in memo['tags']]
        
        properties = {
            "标题": notion_utils.get_title(truncate_string(content_text, 100)),
            "标签": notion_utils.get_multi_select(cleaned_tags),
            "是否置顶": notion_utils.get_select("否" if memo['pin'] == 0 else "是"),
            "slug": notion_utils.get_rich_text(memo['slug']),
            "创建时间": notion_utils.get_date(memo['created_at']),
            "更新时间": notion_utils.get_date(memo['updated_at']),
            "来源": notion_utils.get_select(memo['source'].replace(',', '')[:100]),
            "链接数量": notion_utils.get_number(memo['linked_count']),
        }

        random_cover = random.choice(cover)
        print(f"Random element: {random_cover}")

        try:
            page = self.notion_helper.client.pages.create(
                parent=parent,
                icon=notion_utils.get_icon("https://www.notion.so/icons/target_red.svg"),
                cover=notion_utils.get_icon(random_cover),
                properties=properties,
            )

            self.upload_content_in_chunks(content_md, page['id'])
            print(f"Successfully inserted memo with slug: {memo['slug']}")
        except notion_client.errors.APIResponseError as e:
            print(f"Error inserting memo: {e}")
            print(f"Problematic memo: {memo}")
            print(f"Skipping memo with slug: {memo['slug']}")
        except Exception as e:
            print(f"Unexpected error inserting memo: {e}")
            print(f"Problematic memo: {memo}")
            print(f"Skipping memo with slug: {memo['slug']}")

    def update_memo(self, memo, page_id):
        print("update_memo:", memo)

        content_md = markdownify(memo['content'])
        content_text = html2text.html2text(memo['content'])
        properties = {
            "标题": notion_utils.get_title(truncate_string(content_text, 100)),
            "更新时间": notion_utils.get_date(memo['updated_at']),
            "链接数量": notion_utils.get_number(memo['linked_count']),
            "标签": notion_utils.get_multi_select([self.clean_and_truncate_tag(tag) for tag in memo['tags']]),
            "是否置顶": notion_utils.get_select("否" if memo['pin'] == 0 else "是"),
        }
        page = self.notion_helper.client.pages.update(page_id=page_id, properties=properties)

        self.notion_helper.clear_page_content(page["id"])
        self.upload_content_in_chunks(content_md, page['id'])

    def upload_content_in_chunks(self, content, page_id):
        # Split content into smaller chunks
        chunks = self.split_content(content)
        for chunk in chunks:
            try:
                self.uploader.uploadSingleFileContent(self.notion_helper.client, chunk, page_id)
            except notion_client.errors.APIResponseError as e:
                print(f"Error uploading chunk: {e}")
                print(f"Problematic chunk: {chunk[:100]}...")  # Print first 100 characters of the chunk

    @staticmethod
    def split_content(content, max_length=100):
        lines = content.split('\n')
        chunks = []
        current_chunk = ""
        
        for line in lines:
            if len(current_chunk) + len(line) > max_length:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line + '\n'
            else:
                current_chunk += line + '\n'
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks

    def sync_to_notion(self):
        authorization = os.getenv("FLOMO_TOKEN")
        memo_list = []
        latest_updated_at = "0"

        while True:
            new_memo_list = self.flomo_api.get_memo_list(authorization, latest_updated_at)
            if not new_memo_list:
                break
            memo_list.extend(new_memo_list)
            latest_updated_at = str(int(time.mktime(time.strptime(new_memo_list[-1]['updated_at'], "%Y-%m-%d %H:%M:%S"))))

        notion_memo_list = self.notion_helper.query_all(self.notion_helper.page_id)
        slug_map = {notion_utils.get_rich_text_from_result(notion_memo, "slug"): notion_memo.get("id") for notion_memo in notion_memo_list}

        for memo in memo_list:
            if memo['slug'] in slug_map:
                full_update = os.getenv("FULL_UPDATE", False)
                interval_day = os.getenv("UPDATE_INTERVAL_DAY", 7)
                if not full_update and not is_within_n_days(memo['updated_at'], interval_day):
                    print("is_within_n_days slug:", memo['slug'])
                    continue

                page_id = slug_map[memo['slug']]
                self.update_memo(memo, page_id)
            else:
                self.insert_memo(memo)

if __name__ == "__main__":
    flomo2notion = Flomo2Notion()
    flomo2notion.sync_to_notion()
