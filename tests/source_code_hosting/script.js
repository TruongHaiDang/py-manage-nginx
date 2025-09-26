(function () {
  'use strict';

  /**
   * Update footer year and handle CTA interaction.
   * Designed to run immediately after the DOM loads.
   */
  function initializePage() {
    const footerYearElement = document.getElementById('year');
    if (footerYearElement) {
      footerYearElement.textContent = String(new Date().getFullYear());
    }

    const exploreButton = document.getElementById('explore-button');
    if (exploreButton) {
      exploreButton.addEventListener('click', function handleExploreClick() {
        const featuresSection = document.getElementById('features');
        if (featuresSection) {
          featuresSection.scrollIntoView({ behavior: 'smooth' });
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializePage, { once: true });
  } else {
    initializePage();
  }
})();
