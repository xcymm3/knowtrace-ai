-- Existing KnowTrace installations need an explicit Storage bucket update
-- when support for the legacy .doc and .xls Office formats is enabled.
update storage.buckets
set allowed_mime_types = array[
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/plain',
  'text/markdown',
  'text/csv',
  'image/jpeg',
  'image/png',
  'image/webp'
]
where id = 'knowtrace-assets';
