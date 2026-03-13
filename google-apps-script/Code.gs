const SHEET_NAME = 'Trackers';
const HEADERS = ['Email', 'Product URL', 'Target Price', 'Current Price', 'Date Added'];

function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({ success: true, message: 'DropAlert web app is live.' }))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    e = e || { parameter: {} };
    const email = cleanValue(e.parameter.email);
    const productUrl = cleanValue(e.parameter.productUrl);
    const targetPrice = parsePriceValue(e.parameter.targetPrice);

    if (!email || !productUrl || targetPrice === null) {
      return jsonResponse({
        success: false,
        message: 'Missing or invalid email, product URL, or target price.'
      });
    }

    const sheet = getSheet();
    const currentPrice = fetchCurrentPrice(productUrl);

    sheet.appendRow([
      email,
      productUrl,
      targetPrice,
      currentPrice !== null ? currentPrice : '',
      new Date()
    ]);

    return jsonResponse({
      success: true,
      message: 'Tracking started successfully.',
      currentPrice: currentPrice
    });
  } catch (error) {
    return jsonResponse({
      success: false,
      message: error.message
    });
  }
}

function getSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = spreadsheet.insertSheet(SHEET_NAME);
  }

  const firstRow = sheet.getRange(1, 1, 1, HEADERS.length).getValues()[0];
  const hasHeaders = HEADERS.every(function(header, index) {
    return firstRow[index] === header;
  });

  if (!hasHeaders) {
    sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
    sheet.setFrozenRows(1);
  }

  return sheet;
}

function fetchCurrentPrice(productUrl) {
  const response = UrlFetchApp.fetch(productUrl, {
    followRedirects: true,
    muteHttpExceptions: true,
    headers: {
      'User-Agent': 'Mozilla/5.0 (compatible; DropAlert/1.0; +https://github.com/)'
    }
  });

  if (response.getResponseCode() >= 400) {
    return null;
  }

  const html = response.getContentText();
  return extractPriceFromHtml(html);
}

function extractPriceFromHtml(html) {
  const patterns = [
    /itemprop=["']price["'][^>]*content=["']([^"']+)/gi,
    /property=["']product:price:amount["'][^>]*content=["']([^"']+)/gi,
    /name=["']twitter:data1["'][^>]*content=["']([^"']+)/gi,
    /"price"\s*:\s*"?([0-9]+(?:[.,][0-9]{2})?)"?/gi,
    /"lowPrice"\s*:\s*"?([0-9]+(?:[.,][0-9]{2})?)"?/gi,
    /"priceAmount"\s*:\s*"?([0-9]+(?:[.,][0-9]{2})?)"?/gi,
    /(?:\$|USD\s?)([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)/gi
  ];

  for (let i = 0; i < patterns.length; i += 1) {
    const matches = [];
    let match;

    while ((match = patterns[i].exec(html)) !== null) {
      const parsed = parsePriceValue(match[1]);
      if (parsed !== null) {
        matches.push(parsed);
      }
    }

    if (matches.length > 0) {
      return matches[0];
    }
  }

  return null;
}

function parsePriceValue(value) {
  if (value === undefined || value === null || value === '') {
    return null;
  }

  const normalized = String(value)
    .replace(/&nbsp;/gi, ' ')
    .replace(/[^0-9.,]/g, '')
    .trim();

  if (!normalized) {
    return null;
  }

  let candidate = normalized;
  const hasComma = candidate.indexOf(',') !== -1;
  const hasDot = candidate.indexOf('.') !== -1;

  if (hasComma && hasDot) {
    candidate = candidate.replace(/,/g, '');
  } else if (hasComma && !hasDot) {
    candidate = candidate.replace(/,/g, '.');
  }

  const number = parseFloat(candidate);
  if (!isFinite(number)) {
    return null;
  }

  return Math.round(number * 100) / 100;
}

function cleanValue(value) {
  return value ? String(value).trim() : '';
}

function jsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
