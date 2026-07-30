-- 0011: გამყიდვლის Facebook user-id (ASID) შენახვა — Data Deletion callback-ისთვის.
-- როცა გამყიდველი აპს Facebook-იდან მოხსნის, Meta ამ ID-ს გვიგზავნის; ამ ID-ით
-- ვპოულობთ მის მაღაზიას, ვთიშავთ გვერდს და ვშლით საუბრებს.

alter table public.shops
  add column if not exists facebook_user_id text;

create index if not exists shops_facebook_user_idx
  on public.shops (facebook_user_id);

-- შემოწმება: shops-ს დაემატა facebook_user_id (text, nullable).
