-- Optional demo records for a fresh CommerceLens AI Supabase project.
-- Run only after all migrations. Files and vector chunks are intentionally not
-- fabricated: upload actual or authorized materials through the FastAPI API.

insert into public.research_projects (
  id, name, category, target_platform, target_audience, status
)
values (
  '00000000-0000-0000-0000-000000000001',
  '通勤保温杯选品调研',
  '家居饮具',
  '抖音电商',
  '城市通勤人群',
  'ACTIVE'
)
on conflict (id) do update set
  name = excluded.name,
  category = excluded.category,
  target_platform = excluded.target_platform,
  target_audience = excluded.target_audience,
  status = excluded.status;

insert into public.products (
  id, project_id, role, name, brand_name, price, currency, description, attributes
)
values
  (
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000001',
    'OWN',
    '轻量随行保温杯',
    '自有品牌',
    59.90,
    'CNY',
    '通勤场景候选商品。',
    '{"capacity":"450ml","material":"316不锈钢","sellingPoints":["轻量","防漏"]}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000000102',
    '00000000-0000-0000-0000-000000000001',
    'COMPETITOR',
    '一键开合保温杯',
    '竞品品牌 A',
    49.90,
    'CNY',
    '通勤场景竞品样本。',
    '{"capacity":"480ml","feature":"单手开合"}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000000103',
    '00000000-0000-0000-0000-000000000001',
    'COMPETITOR',
    '极简咖啡随行杯',
    '竞品品牌 B',
    79.00,
    'CNY',
    '咖啡随行场景竞品样本。',
    '{"capacity":"380ml","coating":"陶瓷涂层"}'::jsonb
  )
on conflict (id) do update set
  role = excluded.role,
  name = excluded.name,
  brand_name = excluded.brand_name,
  price = excluded.price,
  currency = excluded.currency,
  description = excluded.description,
  attributes = excluded.attributes;
