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
        print(f"Inserting memo: {memo['slug']}")
        try:
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
            print(f"Random cover: {random_cover}")

            page = self.notion_helper.client.pages.create(
                parent=parent,
                icon=notion_utils.get_icon("https://www.notion.so/icons/target_red.svg"),
                cover=notion_utils.get_icon(random_cover),
                properties=properties,
            )

            self.upload_content_in_chunks(content_md, page['id'])
            print(f"Successfully inserted memo with slug: {memo['slug']}")
        except notion_client.errors.APIResponseError as e:
            print(f"API Error inserting memo: {e}")
            print(f"Skipping memo with slug: {memo['slug']}")
        except Exception as e:
            print(f"Unexpected error inserting memo: {e}")
            print(f"Skipping memo with slug: {memo['slug']}")

    def update_memo(self, memo, page_id):
        print(f"Updating memo: {memo['slug']}")
        try:
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
            print(f"Successfully updated memo with slug: {memo['slug']}")
        except notion_client.errors.APIResponseError as e:
            print(f"API Error updating memo: {e}")
            print(f"Skipping update for memo with slug: {memo['slug']}")
        except Exception as e:
            print(f"Unexpected error updating memo: {e}")
            print(f"Skipping update for memo with slug: {memo['slug']}")

    def upload_content_in_chunks(self, content, page_id):
        chunks = self.split_content(content)
        for i, chunk in enumerate(chunks):
            try:
                self.uploader.uploadSingleFileContent(self.notion_helper.client, chunk, page_id)
                print(f"Uploaded chunk {i+1}/{len(chunks)}")
            except notion_client.errors.APIResponseError as e:
                print(f"API Error uploading chunk {i+1}/{len(chunks)}: {e}")
                print(f"Problematic chunk: {chunk[:100]}...")  # Print first 100 characters of the chunk
            except AttributeError as e:
                print(f"Error parsing content in chunk {i+1}/{len(chunks)}: {e}")
                print(f"Problematic chunk: {chunk[:100]}...")
            except Exception as e:
                print(f"Unexpected error uploading chunk {i+1}/{len(chunks)}: {e}")
                print(f"Problematic chunk: {chunk[:100]}...")

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
        if not authorization:
            print("Error: FLOMO_TOKEN environment variable not set.")
            return

        memo_list = []
        latest_updated_at = "0"

        while True:
            try:
                new_memo_list = self.flomo_api.get_memo_list(authorization, latest_updated_at)
                if not new_memo_list:
                    break
                memo_list.extend(new_memo_list)
                latest_updated_at = str(int(time.mktime(time.strptime(new_memo_list[-1]['updated_at'], "%Y-%m-%d %H:%M:%S"))))
            except Exception as e:
                print(f"Error fetching memo list: {e}")
                break

        notion_memo_list = self.notion_helper.query_all(self.notion_helper.page_id)
        slug_map = {notion_utils.get_rich_text_from_result(notion_memo, "slug"): notion_memo.get("id") for notion_memo in notion_memo_list}

        full_update = os.getenv("FULL_UPDATE", "false").lower() == "true"
        interval_day = int(os.getenv("UPDATE_INTERVAL_DAY", 7))

        for memo in memo_list:
            try:
                if memo['slug'] in slug_map:
                    if not full_update and not is_within_n_days(memo['updated_at'], interval_day):
                        print(f"Skipping memo (not within {interval_day} days): {memo['slug']}")
                        continue

                    page_id = slug_map[memo['slug']]
                    self.update_memo(memo, page_id)
                else:
                    self.insert_memo(memo)
            except Exception as e:
                print(f"Error processing memo: {e}")
                print(f"Skipping problematic memo: {memo['slug']}")

        print("Sync completed.")

if __name__ == "__main__":
    flomo2notion = Flomo2Notion()
    flomo2notion.sync_to_notion()
