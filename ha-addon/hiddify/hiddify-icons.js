// Hiddify VPN — custom icon pack for Home Assistant
// Icon: "Hi" signal bars — the Hiddify logo traced as a 24×24 SVG path
// Usage in HA: hiddify:logo
// Loaded as a Lovelace module resource from /local/hiddify-icons.js

const HIDDIFY_PATH =
  // H-shape (two bars connected by a horizontal crossbar)
  // Left rod of H: x=2-4.5, y=15-21
  // Right rod of H: x=5.5-8, y=12-21
  // Crossbar: y=17.5-19, spanning both rods
  "M2,21V15H4.5V17.5H5.5V12H8V21H5.5V19H4.5V21Z" +
  // Middle ascending bar: x=10-13, y=9-21
  "M10,21V9H13V21Z" +
  // i-bar: x=15-17.5, y=9-21
  "M15,21V9H17.5V21Z" +
  // i-dot: x=16-20, y=4-7.5  (offset right — the dot of the "i")
  "M16,4H20V7.5H16Z";

window.customIcons = window.customIcons || {};
window.customIcons["hiddify"] = {
  getIcon: async (name) => {
    if (name === "logo") {
      return { path: HIDDIFY_PATH };
    }
    return { path: "" };
  },
};
