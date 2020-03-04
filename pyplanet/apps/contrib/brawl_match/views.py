from pyplanet.views.generics.list import ManualListView
from pyplanet.apps.core.maniaplanet.models import Map

class BrawlMapListView(ManualListView):
	model = Map
	title = 'Maps available to ban'
	icon_style = 'Icons128x128_1'
	icon_substyle = 'Browse'
	# List of map uid's that the competition uses.
	map_list = []

	async def get_fields(self):
		return [
			{
				'name': '#',
				'index': 'index',
				'sorting': True,
				'searching': False,
				'width': 10,
				'type': 'label'
			},
			{
				'name': 'Name',
				'index': 'name',
				'sorting': True,
				'searching': True,
				'search_strip_styles': True,
				'width': 90,
				'type': 'label',
				'action': self.action_ban
			},
			{
				'name': 'Author',
				'index': 'author_login',
				'sorting': True,
				'searching': True,
				'search_strip_styles': True,
				'renderer': lambda row, field:
				row['author_login'],
				'width': 45,
			}
		]

	def __init__(self, app, maps):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.map_list = maps

	async def get_data(self):
		items = []
		for map_index, map_uid in enumerate(self.map_list, start=1):
			map = await self.app.instance.map_manager.get_map(map_uid)
			map_name = map.name
			map_author = map.author_login

			items.append({
				'index': map_index,
				'name': map_name,
				'author_login': map_author
			})
		return items



	async def action_ban(self, player, values, map_info, **kwargs):
		await self.app.remove_map_from_match(map_info)
		await self.app.next_ban()
		await self.destroy()
