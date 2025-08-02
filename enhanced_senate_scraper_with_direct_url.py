import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import json
import re
import os

# Add the parent directory to the path so we can import the extractor
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Try to import the working extractor with multiple possible names
extractor = None
try:
    from robust_senate_extractor import EnhancedSenateExtractor
    extractor = EnhancedSenateExtractor
except ImportError:
    try:
        from enhanced_senate_extractor import EnhancedSenateExtractor
        extractor = EnhancedSenateExtractor
    except ImportError:
        try:
            # If the file is in the same directory but not recognized as a module
            # We'll import it directly
            import importlib.util
            spec = importlib.util.spec_from_file_location("robust_senate_extractor", "robust_senate_extractor.py")
            robust_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(robust_module)
            extractor = robust_module.EnhancedSenateExtractor
        except Exception as e:
            print(f"Could not import the extractor: {e}")
            sys.exit(1)

if extractor is None:
    print("Could not find the Senate extractor module. Make sure robust_senate_extractor.py is in the same directory.")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('C:\\EMPIRE\\SATORI_Scraper\\enhanced_senate_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class EnhancedSenateScraperWithDirectURL(extractor):
    def __init__(self):
        super().__init__()
        self.base_dir = Path("C:\\EMPIRE\\SATORI_Scraper")
        self.raw_dir = self.base_dir / "data" / "raw" / "senate"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session_established = False
        
        # List of known report URLs that might not appear in search results
        self.known_report_urls = [
            "https://efdsearch.senate.gov/search/view/ptr/0bf421b2-cf4e-40d8-9c9f-98ba5e535c6c/"  # McCormick report
        ]
        
    def establish_session_once(self):
        """Establish session only once and reuse it"""
        if not self.session_established:
            logger.info("Establishing session with Senate website...")
            
            # Strategy 1: Standard Selenium approach - copied from working extractor
            try:
                self.driver.get(f"{self.base_url}/search/")
                time.sleep(2)
                
                # Accept agreement - using the exact approach from the working extractor
                agreement_checkbox = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "agree_statement"))
                )
                agreement_checkbox.click()
                logger.info("Accepted agreement via Selenium")
                
                # Transfer cookies to requests session
                for cookie in self.driver.get_cookies():
                    self.session.cookies.set(cookie['name'], cookie['value'])
                
                self.session_established = True
                return True
            except Exception as e:
                logger.warning(f"Selenium session establishment failed: {e}")
            
            # Strategy 2: Direct requests approach - copied from working extractor
            try:
                logger.info("Trying direct requests approach...")
                response = self.session.get(f"{self.base_url}/search/")
                if "agree_statement" in response.text:
                    # Find agreement form and submit
                    soup = BeautifulSoup(response.text, 'html.parser')
                    agreement_form = soup.find('form', {'id': 'agreement_form'})
                    if agreement_form:
                        action = agreement_form.get('action')
                        if action:
                            response = self.session.post(
                                f"{self.base_url}{action}",
                                data={'agree_statement': 'agree'}
                            )
                            if response.status_code == 200:
                                logger.info("Accepted agreement via requests")
                                self.session_established = True
                                return True
            except Exception as e:
                logger.warning(f"Requests session establishment failed: {e}")
            
            return False
        else:
            logger.info("Session already established")
            return True
        
    def process_direct_url(self, url):
        """Process a report directly from its URL"""
        logger.info(f"Processing report directly from URL: {url}")
        
        # Establish session if needed
        if not self.establish_session_once():
            logger.error("Failed to establish session")
            return None
        
        # Create a report data object
        report_data = {
            'name': 'Direct URL Report',
            'link': url,
            'date_filed': 'Unknown',
            'office': 'Unknown',
            'report_type': 'Periodic Transaction Report'
        }
        
        # Process the report using the existing method
        result = self.process_report(report_data)
        
        if result:
            # Extract the actual name from the report content if available
            if 'transactions' in result and result['transactions']:
                # Try to get the name from the first transaction
                first_transaction = result['transactions'][0]
                if 'owner' in first_transaction:
                    result['name'] = f"Direct URL Report ({first_transaction['owner']})"
            
            # Save the result
            filename = f"direct_url_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = self.raw_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
            
            logger.info(f"Successfully processed direct URL report: {url}")
            return result
        else:
            logger.error(f"Failed to process direct URL report: {url}")
            return None
    
    def search_reports(self, start_date, end_date):
        """Search for reports within date range"""
        logger.info(f"Searching for reports from {start_date} to {end_date}")
        
        # Use the establish_session_once method to establish or reuse session
        if not self.establish_session_once():
            logger.error("Failed to establish session")
            return []
        
        # Navigate to search page (in case we're not already there)
        self.driver.get(f"{self.base_url}/search/")
        time.sleep(3)
        
        # Select report type (Periodic Transaction Report)
        try:
            ptr_checkbox = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@value='7' and @name='report_type']"))
            )
            ptr_checkbox.click()
            logger.info("Selected Periodic Transaction Report checkbox")
            time.sleep(3)  # Longer wait after selecting report type to ensure date fields load
        except Exception as e:
            logger.error(f"Failed to select report type: {e}")
            return []
        
        # Set date range with multiple strategies and explicit waits
        date_fields_found = False
        
        # Strategy 1: Try by name attribute with explicit wait
        try:
            logger.info("Trying to find date fields by name attribute with explicit wait")
            from_date = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "fromDate"))
            )
            to_date = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "toDate"))
            )
            logger.info("Found date fields by name attribute")
            date_fields_found = True
        except Exception as e:
            logger.warning(f"Could not find date fields by name: {e}")
        
        # Strategy 2: Try by ID attribute if name fails
        if not date_fields_found:
            try:
                logger.info("Trying to find date fields by ID attribute")
                from_date = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "fromDate"))
                )
                to_date = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "toDate"))
                )
                logger.info("Found date fields by ID attribute")
                date_fields_found = True
            except Exception as e:
                logger.warning(f"Could not find date fields by ID: {e}")
        
        # Strategy 3: Try by CSS selector if others fail
        if not date_fields_found:
            try:
                logger.info("Trying to find date fields by CSS selector")
                from_date = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name*='from'], input[id*='from']"))
                )
                to_date = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name*='to'], input[id*='to']"))
                )
                logger.info("Found date fields by CSS selector")
                date_fields_found = True
            except Exception as e:
                logger.warning(f"Could not find date fields by CSS selector: {e}")
        
        # If we found the date fields, set the values
        if date_fields_found:
            try:
                # Clear and set the dates using JavaScript for better reliability
                logger.info("Setting date values using JavaScript")
                self.driver.execute_script(f"document.getElementById('fromDate').value = '{start_date}';")
                self.driver.execute_script(f"document.getElementById('toDate').value = '{end_date}';")
                
                # Verify the dates were set correctly
                actual_from_date = self.driver.execute_script("return document.getElementById('fromDate').value;")
                actual_to_date = self.driver.execute_script("return document.getElementById('toDate').value;")
                
                logger.info(f"Set date range from {actual_from_date} to {actual_to_date}")
                
                # If JavaScript didn't work, try the traditional method
                if actual_from_date != start_date or actual_to_date != end_date:
                    logger.warning("JavaScript date setting failed, trying traditional method")
                    from_date.clear()
                    from_date.send_keys(start_date)
                    to_date.clear()
                    to_date.send_keys(end_date)
                
                # Wait a moment after setting dates
                time.sleep(2)
            except Exception as e:
                logger.error(f"Failed to set date range: {e}")
                return []
        else:
            # If we couldn't find the date fields with any strategy, take a screenshot for debugging
            try:
                screenshot_path = f"C:\\EMPIRE\\SATORI_Scraper\\date_fields_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Saved screenshot to {screenshot_path}")
                
                # Save HTML for debugging
                html_path = f"C:\\EMPIRE\\SATORI_Scraper\\date_fields_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                logger.info(f"Saved HTML to {html_path}")
            except Exception as e:
                logger.error(f"Failed to save debug files: {e}")
            
            logger.error("Could not find date fields with any strategy")
            return []
        
        # Submit search with explicit wait
        try:
            logger.info("Looking for 'Search Reports' button")
            
            # Try multiple approaches to find and click the search button
            search_button = None
            
            # Approach 1: Look for button with exact text "Search Reports"
            try:
                search_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Search Reports')]"))
                )
                logger.info("Found 'Search Reports' button by text")
            except:
                logger.info("Could not find button by text 'Search Reports'")
            
            # Approach 2: Look for any button containing "Search"
            if not search_button:
                try:
                    search_button = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Search')]"))
                    )
                    logger.info("Found button containing 'Search' text")
                except:
                    logger.info("Could not find button containing 'Search' text")
            
            # Approach 3: Look for blue button (often search buttons are blue)
            if not search_button:
                try:
                    search_button = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-primary, button[type='submit']"))
                    )
                    logger.info("Found button by CSS class or type")
                except:
                    logger.info("Could not find button by CSS class or type")
            
            # If we found a button, try to click it
            if search_button:
                # Make sure the button is visible and clickable
                try:
                    # Scroll to the button
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", search_button)
                    time.sleep(1)
                    
                    # Try regular click
                    search_button.click()
                    logger.info("Successfully clicked the search button")
                except Exception as click_error:
                    logger.warning(f"Regular click failed: {click_error}")
                    # Try JavaScript click
                    try:
                        self.driver.execute_script("arguments[0].click();", search_button)
                        logger.info("Successfully clicked the search button using JavaScript")
                    except Exception as js_error:
                        logger.error(f"JavaScript click also failed: {js_error}")
                        return []
            else:
                logger.error("Could not find the search button")
                return []
                
            # Wait for results page to load
            logger.info("Waiting for results page to load")
            time.sleep(5)  # Initial wait
            
            # Then wait for the results table to appear
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "table"))
            )
            logger.info("Results page loaded successfully")
            
            # Additional wait to ensure all content is loaded
            time.sleep(3)
            
        except Exception as e:
            logger.error(f"Error in search button process: {e}")
            return []
        
        # Extract report links using a method that handles dynamic loading
        reports = self.extract_report_links_dynamic(start_date, end_date)
        logger.info(f"Found {len(reports)} reports")
        return reports
    
    def extract_report_links_dynamic(self, start_date, end_date):
        """Extract report links using a method that handles dynamic DataTable loading"""
        reports = []
        
        # Save HTML for debugging
        try:
            html_path = f"C:\\EMPIRE\\SATORI_Scraper\\results_page_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.info(f"Saved results page HTML to {html_path}")
        except Exception as e:
            logger.error(f"Failed to save HTML: {e}")
        
        # Wait for the DataTable to finish loading
        logger.info("Waiting for DataTable to finish loading...")
        
        # Check if the "Processing" indicator is visible and wait for it to disappear
        try:
            processing_indicator = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.ID, "filedReports_processing"))
            )
            
            # Wait for the processing indicator to disappear
            WebDriverWait(self.driver, 30).until(
                EC.invisibility_of_element_located((By.ID, "filedReports_processing"))
            )
            logger.info("DataTables processing completed")
        except Exception as e:
            logger.warning(f"Could not find or wait for processing indicator: {e}")
        
        # Additional wait to ensure data is loaded
        time.sleep(3)
        
        # Try multiple strategies to extract the data
        
        # Strategy 1: JavaScript-based extraction (most reliable for DataTables)
        try:
            logger.info("Trying JavaScript-based extraction from DataTable...")
            
            # Execute JavaScript to get the DataTable data
            js_script = """
            var table = #filedReports.DataTable();
            var data = table.data().toArray();
            return JSON.stringify(data);
            """
            
            data_json = self.driver.execute_script(js_script)
            data = json.loads(data_json)
            
            logger.info(f"JavaScript extraction returned {len(data)} records")
            
            # Process the data from the DataTable
            for record in data:
                # Extract the report link
                link = None
                if len(record) >= 5:  # Assuming the link is in the 4th column (index 3)
                    link_html = record[3]
                    soup = BeautifulSoup(link_html, 'html.parser')
                    link_elem = soup.find('a')
                    if link_elem and 'href' in link_elem.attrs:
                        link = f"{self.base_url}{link_elem['href']}"
                
                if link:
                    report = {
                        'name': f"{record[1]} {record[0]}",  # First Name, Last Name
                        'office': record[2],  # Office (Filer Type)
                        'report_type': record[3].strip(),  # Report Type
                        'date_filed': record[4],  # Date Received/Filed
                        'link': link
                    }
                    reports.append(report)
            
            if reports:
                logger.info(f"Successfully extracted {len(reports)} reports using JavaScript extraction")
                return reports
        except Exception as e:
            logger.warning(f"JavaScript extraction failed: {e}")
        
        # Strategy 2: Direct API approach
        try:
            logger.info("Trying direct API approach...")
            
            # Format dates for the API
            start_date_api = f"{start_date} 00:00:00"
            end_date_api = f"{end_date} 23:59:59"
            
            # Make the same AJAX request that the DataTable makes
            response = self.session.post(
                f"{self.base_url}/search/report/data/",
                data={
                    "report_types": "[7]",
                    "filer_types": "[]",
                    "submitted_start_date": start_date_api,
                    "submitted_end_date": end_date_api,
                    "candidate_state": "",
                    "senator_state": "",
                    "office_id": "",
                    "first_name": "",
                    "last_name": ""
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"API response received with {len(data.get('data', []))} records")
                
                # Process the data from the API response
                for record in data.get('data', []):
                    # Extract the report link
                    link = None
                    if len(record) >= 5:  # Assuming the link is in the 5th column (index 4)
                        link_html = record[4]
                        soup = BeautifulSoup(link_html, 'html.parser')
                        link_elem = soup.find('a')
                        if link_elem and 'href' in link_elem.attrs:
                            link = f"{self.base_url}{link_elem['href']}"
                    
                    if link:
                        report = {
                            'name': f"{record[1]} {record[0]}",  # Last Name, First Name
                            'office': record[2],  # Office (Filer Type)
                            'report_type': record[3],  # Report Type
                            'date_filed': record[5],  # Date Received/Filed
                            'link': link
                        }
                        reports.append(report)
                
                if reports:
                    logger.info(f"Successfully extracted {len(reports)} reports using API approach")
                    return reports
            else:
                logger.warning(f"API request failed with status {response.status_code}")
        except Exception as e:
            logger.warning(f"API approach failed: {e}")
        
        # Strategy 3: Parse the loaded table
        try:
            logger.info("Trying to parse the loaded table...")
            
            # Re-parse the page after the data has been loaded
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Find the results table
            table = soup.find('table', id='filedReports')
            if not table:
                logger.error("Table with id 'filedReports' not found")
                return reports
            
            # Find all rows in the table body
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
            else:
                rows = table.find_all('tr')[1:]  # Skip header row if no tbody
            
            # Skip the "No matching reports" row
            if rows and len(rows) == 1 and "no matching filed reports" in rows[0].get_text(strip=True).lower():
                logger.info("No reports found for the specified date range")
                return reports
            
            logger.info(f"Found {len(rows)} rows in the table")
            
            for i, row in enumerate(rows):
                try:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 5:  # We expect 5 cells: First Name, Last Name, Office, Report Type, Date
                        # Extract name from first two cells
                        first_name = cells[0].get_text(strip=True)
                        last_name = cells[1].get_text(strip=True)
                        name = f"{first_name} {last_name}"
                        
                        # Extract office
                        office = cells[2].get_text(strip=True)
                        
                        # The link is in the 4th cell (index 3) - Report Type
                        report_type_cell = cells[3]
                        link_elem = report_type_cell.find('a')
                        
                        if link_elem and 'href' in link_elem.attrs:
                            # Extract report type from the link text
                            report_type = link_elem.get_text(strip=True)
                            
                            # Extract date filed from the 5th cell (index 4)
                            date_filed = cells[4].get_text(strip=True)
                            
                            report = {
                                'name': name,
                                'office': office,
                                'report_type': report_type,
                                'date_filed': date_filed,
                                'link': self.base_url + link_elem['href']
                            }
                            reports.append(report)
                            logger.debug(f"Added report: {report['name']} - {report['report_type']}")
                        else:
                            logger.warning(f"No link found in report type cell for row {i}")
                    else:
                        logger.warning(f"Row {i} has only {len(cells)} cells, expected at least 5")
                except Exception as e:
                    logger.error(f"Error parsing row {i}: {e}")
            
            if reports:
                logger.info(f"Successfully extracted {len(reports)} reports by parsing the table")
                return reports
        except Exception as e:
            logger.warning(f"Table parsing approach failed: {e}")
        
        logger.info(f"Found {len(reports)} reports total")
        return reports
    
    def process_reports(self, reports, batch_name):
        """Process a list of reports"""
        logger.info(f"Processing {len(reports)} reports for batch {batch_name}")
        
        # Create batch directory
        batch_dir = self.raw_dir / batch_name
        batch_dir.mkdir(exist_ok=True)
        
        processed_reports = []
        
        for i, report in enumerate(reports):
            logger.info(f"Processing report {i+1}/{len(reports)}: {report['name']}")
            
            # Process the report using the existing method
            result = self.process_report(report)
            
            if result:
                # Save the result
                filename = f"{report['name'].replace(' ', '_').replace(',', '')}.json"
                filepath = batch_dir / filename
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2)
                
                processed_reports.append(result)
                
                # Log summary
                logger.info(f"Extracted {result['transaction_count']} transactions")
            else:
                logger.error(f"Failed to process report: {report['name']}")
            
            # Rate limiting
            time.sleep(1)
        
        # Save batch summary
        summary = {
            'batch_name': batch_name,
            'processing_date': datetime.now().isoformat(),
            'total_reports': len(reports),
            'successful_reports': len(processed_reports),
            'total_transactions': sum(r['transaction_count'] for r in processed_reports),
            'reports': processed_reports
        }
        
        summary_file = batch_dir / "summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Batch {batch_name} completed: {len(processed_reports)}/{len(reports)} reports processed")
    
    def run_historical_scrape(self, start_year=2018, end_year=None):
        """Scrape historical data from start_year to end_year"""
        if end_year is None:
            end_year = datetime.now().year
        
        logger.info(f"Starting historical scrape from {start_year} to {end_year}")
        
        # Establish session once at the beginning
        if not self.establish_session_once():
            logger.error("Failed to establish session")
            return False
        
        # Iterate through years
        for year in range(start_year, end_year + 1):
            logger.info(f"Processing year: {year}")
            
            # Iterate through months
            for month in range(1, 13):
                # Skip future months
                if year == end_year and month > datetime.now().month:
                    continue
                
                logger.info(f"Processing {year}-{month:02d}")
                
                # Format dates for Senate search
                start_date = f"01/{month:02d}/{year}"
                
                # Calculate end date (last day of month)
                if month == 12:
                    end_date = f"31/12/{year}"
                else:
                    end_date = f"30/{month+1:02d}/{year}"
                
                # Get reports for this month
                reports = self.search_reports(start_date, end_date)
                
                if reports:
                    self.process_reports(reports, f"{year}-{month:02d}")
                
                # Rate limiting - be respectful to the server
                time.sleep(2)
        
        logger.info("Historical scrape completed")
        return True
    
    def run_daily_scrape(self):
        """Run daily scraper to check for new reports (today and yesterday)"""
        logger.info("Starting daily scrape")
        
        # Establish session once at the beginning
        if not self.establish_session_once():
            logger.error("Failed to establish session")
            return False
        
        # Get today and yesterday dates
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        
        # Format dates
        today_str = today.strftime("%m/%d/%Y")
        yesterday_str = yesterday.strftime("%m/%d/%Y")
        
        # Get reports for today
        today_reports = self.search_reports(today_str, today_str)
        if today_reports:
            logger.info(f"Found {len(today_reports)} reports for today")
            self.process_reports(today_reports, "daily")
        
        # Get reports for yesterday
        yesterday_reports = self.search_reports(yesterday_str, yesterday_str)
        if yesterday_reports:
            logger.info(f"Found {len(yesterday_reports)} reports for yesterday")
            self.process_reports(yesterday_reports, "daily")
        
        # If no reports found, try processing known URLs
        if not today_reports and not yesterday_reports:
            logger.info("No reports found for today and yesterday, trying known URLs")
            
            for url in self.known_report_urls:
                logger.info(f"Processing known URL: {url}")
                result = self.process_direct_url(url)
                if result:
                    logger.info(f"Successfully processed known URL: {url}")
                else:
                    logger.error(f"Failed to process known URL: {url}")
                
                # Rate limiting
                time.sleep(1)
        
        logger.info("Daily scrape completed")
        return True

def main():
    parser = argparse.ArgumentParser(description='Enhanced Senate Trading Data Scraper with Direct URL Support')
    parser.add_argument('--mode', choices=['historical', 'daily', 'direct'], required=True,
                        help='Scraping mode: historical, daily, or direct')
    parser.add_argument('--start-year', type=int, default=2018,
                        help='Start year for historical scraping (default: 2018)')
    parser.add_argument('--end-year', type=int,
                        help='End year for historical scraping (default: current year)')
    parser.add_argument('--url', type=str,
                        help='URL to process directly (only for direct mode)')
    
    args = parser.parse_args()
    
    scraper = EnhancedSenateScraperWithDirectURL()
    
    try:
        if args.mode == 'historical':
            success = scraper.run_historical_scrape(args.start_year, args.end_year)
        elif args.mode == 'daily':
            success = scraper.run_daily_scrape()
        else:  # direct
            if args.url:
                success = scraper.process_direct_url(args.url) is not None
            else:
                logger.error("URL must be provided for direct mode")
                success = False
        
        if success:
            print("Scraping completed successfully")
        else:
            print("Scraping failed")
    finally:
        scraper.close()

if __name__ == "__main__":
    main()
