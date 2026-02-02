import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';

export default defineConfig({
  integrations: [mdx()],
  srcDir: 'src',
  site: 'https://godstorm91.github.io/note-site',
  base: '/note-site',
});
